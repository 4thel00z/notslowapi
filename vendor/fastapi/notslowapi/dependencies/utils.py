import dataclasses
import inspect
import sys
from collections.abc import (
    AsyncGenerator,
    AsyncIterable,
    AsyncIterator,
    Callable,
    Generator,
    Iterable,
    Iterator,
    Mapping,
    Sequence,
)
from contextlib import AsyncExitStack, contextmanager
from copy import copy, deepcopy
from dataclasses import dataclass
from typing import (
    Annotated,
    Any,
    ForwardRef,
    Literal,
    Union,
    cast,
    get_args,
    get_origin,
)

from notslowapi import params
from notslowapi._compat import (
    ModelField,
    RequiredParam,
    Undefined,
    copy_field_info,
    create_body_model,
    evaluate_forwardref,
    field_annotation_is_scalar,
    field_annotation_is_scalar_sequence,
    get_cached_model_fields,
    get_missing_field_error,
    is_bytes_or_nonable_bytes_annotation,
    is_bytes_sequence_annotation,
    is_scalar_field,
    is_uploadfile_or_nonable_uploadfile_annotation,
    is_uploadfile_sequence_annotation,
    lenient_issubclass,
    sequence_types,
    serialize_sequence_value,
    value_is_sequence,
)
from notslowapi.background import BackgroundTasks
from notslowapi.concurrency import (
    asynccontextmanager,
    contextmanager_in_threadpool,
)
from notslowapi.dependencies.models import (
    Dependant,
    _get_cache_key,
    _get_computed_scope,
    _get_oauth_scopes,
    _is_async_gen_callable,
    _is_gen_callable,
    _UsesScopesCache,
    dependant_cache_key,
    dependant_call_kinds,
    dependant_is_leaf,
    dependant_is_simple,
    dependant_needs_response,
)
from notslowapi.exceptions import DependencyScopeError
from notslowapi.logger import logger
from notslowapi.security.oauth2 import SecurityScopes
from notslowapi.starlette.background import BackgroundTasks as StarletteBackgroundTasks
from notslowapi.starlette.concurrency import run_in_threadpool
from notslowapi.starlette.datastructures import (
    FormData,
    Headers,
    ImmutableMultiDict,
    QueryParams,
    UploadFile,
    parse_query_string,
)
from notslowapi.starlette.requests import HTTPConnection, Request
from notslowapi.starlette.responses import Response
from notslowapi.starlette.websockets import WebSocket
from notslowapi.types import DependencyCacheKey
from notslowapi.utils import create_model_field, get_path_param_names
from pydantic import BaseModel
from pydantic.fields import FieldInfo
from typing_inspection.typing_objects import is_typealiastype

multipart_not_installed_error = (
    'Form data requires "python-multipart" to be installed. \n'
    'You can install "python-multipart" with: \n\n'
    "pip install python-multipart\n"
)
multipart_incorrect_install_error = (
    'Form data requires "python-multipart" to be installed. '
    'It seems you installed "multipart" instead. \n'
    'You can remove "multipart" with: \n\n'
    "pip uninstall multipart\n\n"
    'And then install "python-multipart" with: \n\n'
    "pip install python-multipart\n"
)


AnyCallable = Callable[..., Any]


def ensure_multipart_is_installed() -> None:
    try:
        from python_multipart import __version__

        # Import an attribute that can be mocked/deleted in testing
        assert __version__ > "0.0.12"
    except (ImportError, AssertionError):
        try:
            # __version__ is available in both multiparts, and can be mocked
            from multipart import (  # type: ignore[no-redef,import-untyped]
                __version__,
            )

            assert __version__
            try:
                # parse_options_header is only available in the right multipart
                from multipart.multipart import (  # type: ignore[import-untyped]
                    parse_options_header,
                )

                assert parse_options_header
            except ImportError:
                logger.error(multipart_incorrect_install_error)
                raise RuntimeError(multipart_incorrect_install_error) from None
        except ImportError:
            logger.error(multipart_not_installed_error)
            raise RuntimeError(multipart_not_installed_error) from None


def get_parameterless_sub_dependant(*, depends: params.Depends, path: str) -> Dependant:
    assert callable(depends.dependency), (
        "A parameter-less dependency must have a callable dependency"
    )
    own_oauth_scopes: list[str] = []
    if isinstance(depends, params.Security) and depends.scopes:
        own_oauth_scopes.extend(depends.scopes)
    return get_dependant(
        path=path,
        call=depends.dependency,
        scope=depends.scope,
        own_oauth_scopes=own_oauth_scopes,
    )


def _get_flat_body_params(dependant: Dependant) -> list[ModelField]:
    body_params: list[ModelField] = []
    dependants = [dependant]
    while dependants:
        current_dependant = dependants.pop()
        body_params.extend(current_dependant.body_params)
        dependants.extend(reversed(current_dependant.dependencies))
    return body_params


def _get_flat_fields_from_params(fields: list[ModelField]) -> list[ModelField]:
    if not fields:
        return fields
    first_field = fields[0]
    if len(fields) == 1 and lenient_issubclass(
        first_field.field_info.annotation, BaseModel
    ):
        fields_to_extract = get_cached_model_fields(first_field.field_info.annotation)
        return fields_to_extract
    return fields


def get_flat_params(dependant: Dependant) -> list[ModelField]:
    path_params: list[ModelField] = []
    query_params: list[ModelField] = []
    header_params: list[ModelField] = []
    cookie_params: list[ModelField] = []
    visited: list[DependencyCacheKey] = []
    uses_scopes_cache: _UsesScopesCache = {}
    dependants = [dependant]
    while dependants:
        current_dependant = dependants.pop()
        cache_key = _get_cache_key(
            dependant=current_dependant,
            uses_scopes_cache=uses_scopes_cache,
        )
        if cache_key in visited:
            continue
        visited.append(cache_key)
        path_params.extend(current_dependant.path_params)
        query_params.extend(current_dependant.query_params)
        header_params.extend(current_dependant.header_params)
        cookie_params.extend(current_dependant.cookie_params)
        dependants.extend(reversed(current_dependant.dependencies))
    path_params = _get_flat_fields_from_params(path_params)
    query_params = _get_flat_fields_from_params(query_params)
    header_params = _get_flat_fields_from_params(header_params)
    cookie_params = _get_flat_fields_from_params(cookie_params)
    return path_params + query_params + header_params + cookie_params


def _get_signature(call: Callable[..., Any]) -> inspect.Signature:
    try:
        signature = inspect.signature(call, eval_str=True)
    except NameError:
        # Handle type annotations with if TYPE_CHECKING, not used by FastAPI
        # e.g. dependency return types
        if sys.version_info >= (3, 14):
            from annotationlib import Format

            signature = inspect.signature(call, annotation_format=Format.FORWARDREF)
        else:
            signature = inspect.signature(call)
    return signature


def get_typed_signature(call: Callable[..., Any]) -> inspect.Signature:
    signature = _get_signature(call)
    unwrapped = inspect.unwrap(call)
    globalns = getattr(unwrapped, "__globals__", {})
    typed_params = [
        inspect.Parameter(
            name=param.name,
            kind=param.kind,
            default=param.default,
            annotation=get_typed_annotation(param.annotation, globalns),
        )
        for param in signature.parameters.values()
    ]
    typed_signature = inspect.Signature(typed_params)
    return typed_signature


def get_typed_annotation(annotation: Any, globalns: dict[str, Any]) -> Any:
    if isinstance(annotation, str):
        annotation = ForwardRef(annotation)
        annotation = evaluate_forwardref(annotation, globalns, globalns)
        if annotation is type(None):
            return None
    return annotation


def get_typed_return_annotation(call: Callable[..., Any]) -> Any:
    signature = _get_signature(call)
    unwrapped = inspect.unwrap(call)
    annotation = signature.return_annotation

    if annotation is inspect.Signature.empty:
        return None

    globalns = getattr(unwrapped, "__globals__", {})
    return get_typed_annotation(annotation, globalns)


_STREAM_ORIGINS = {
    AsyncIterable,
    AsyncIterator,
    AsyncGenerator,
    Iterable,
    Iterator,
    Generator,
}


def get_stream_item_type(annotation: Any) -> Any | None:
    origin = get_origin(annotation)
    if origin is not None and origin in _STREAM_ORIGINS:
        type_args = get_args(annotation)
        if type_args:
            return type_args[0]
        return Any
    return None


def get_dependant(
    *,
    path: str,
    call: Callable[..., Any],
    name: str | None = None,
    own_oauth_scopes: list[str] | None = None,
    parent_oauth_scopes: list[str] | None = None,
    use_cache: bool = True,
    scope: Literal["function", "request"] | None = None,
) -> Dependant:
    dependant = Dependant(
        call=call,
        name=name,
        path=path,
        use_cache=use_cache,
        scope=scope,
        own_oauth_scopes=own_oauth_scopes,
        parent_oauth_scopes=parent_oauth_scopes,
    )
    current_scopes = (parent_oauth_scopes or []) + (own_oauth_scopes or [])
    path_param_names = get_path_param_names(path)
    endpoint_signature = get_typed_signature(call)
    signature_params = endpoint_signature.parameters
    for param_name, param in signature_params.items():
        is_path_param = param_name in path_param_names
        param_details = analyze_param(
            param_name=param_name,
            annotation=param.annotation,
            value=param.default,
            is_path_param=is_path_param,
        )
        if param_details.depends is not None:
            assert param_details.depends.dependency
            if (
                (
                    _is_gen_callable(dependant.call)
                    or _is_async_gen_callable(dependant.call)
                )
                and _get_computed_scope(dependant=dependant) == "request"
                and param_details.depends.scope == "function"
            ):
                assert dependant.call
                call_name = getattr(dependant.call, "__name__", "<unnamed_callable>")
                raise DependencyScopeError(
                    f'The dependency "{call_name}" has a scope of '
                    '"request", it cannot depend on dependencies with scope "function".'
                )
            sub_own_oauth_scopes: list[str] = []
            if isinstance(param_details.depends, params.Security):
                if param_details.depends.scopes:
                    sub_own_oauth_scopes = list(param_details.depends.scopes)
            sub_dependant = get_dependant(
                path=path,
                call=param_details.depends.dependency,
                name=param_name,
                own_oauth_scopes=sub_own_oauth_scopes,
                parent_oauth_scopes=current_scopes,
                use_cache=param_details.depends.use_cache,
                scope=param_details.depends.scope,
            )
            dependant.dependencies.append(sub_dependant)
            continue
        if add_non_field_param_to_dependency(
            param_name=param_name,
            type_annotation=param_details.type_annotation,
            dependant=dependant,
        ):
            assert param_details.field is None, (
                f"Cannot specify multiple FastAPI annotations for {param_name!r}"
            )
            continue
        assert param_details.field is not None
        if isinstance(param_details.field.field_info, params.Body):
            dependant.body_params.append(param_details.field)
        else:
            add_param_to_fields(field=param_details.field, dependant=dependant)
    return dependant


def add_non_field_param_to_dependency(
    *, param_name: str, type_annotation: Any, dependant: Dependant
) -> bool | None:
    if lenient_issubclass(type_annotation, Request):
        dependant.request_param_name = param_name
        return True
    elif lenient_issubclass(type_annotation, WebSocket):
        dependant.websocket_param_name = param_name
        return True
    elif lenient_issubclass(type_annotation, HTTPConnection):
        dependant.http_connection_param_name = param_name
        return True
    elif lenient_issubclass(type_annotation, Response):
        dependant.response_param_name = param_name
        return True
    elif lenient_issubclass(type_annotation, StarletteBackgroundTasks):
        dependant.background_tasks_param_name = param_name
        return True
    elif lenient_issubclass(type_annotation, SecurityScopes):
        dependant.security_scopes_param_name = param_name
        return True
    return None


@dataclass
class ParamDetails:
    type_annotation: Any
    depends: params.Depends | None
    field: ModelField | None


def analyze_param(
    *,
    param_name: str,
    annotation: Any,
    value: Any,
    is_path_param: bool,
) -> ParamDetails:
    field_info = None
    depends = None
    type_annotation: Any = Any
    use_annotation: Any = Any
    if is_typealiastype(annotation):
        # unpack in case PEP 695 type syntax is used
        annotation = annotation.__value__
    if annotation is not inspect.Signature.empty:
        use_annotation = annotation
        type_annotation = annotation
    # Extract Annotated info
    if get_origin(use_annotation) is Annotated:
        annotated_args = get_args(annotation)
        type_annotation = annotated_args[0]
        fastapi_annotations = [
            arg
            for arg in annotated_args[1:]
            if isinstance(arg, (FieldInfo, params.Depends))
        ]
        fastapi_specific_annotations = [
            arg
            for arg in fastapi_annotations
            if isinstance(
                arg,
                (
                    params.Param,
                    params.Body,
                    params.Depends,
                ),
            )
        ]
        if fastapi_specific_annotations:
            fastapi_annotation: FieldInfo | params.Depends | None = (
                fastapi_specific_annotations[-1]
            )
        else:
            fastapi_annotation = None
        # Set default for Annotated FieldInfo
        if isinstance(fastapi_annotation, FieldInfo):
            # Copy `field_info` because we mutate `field_info.default` below.
            field_info = copy_field_info(
                field_info=fastapi_annotation,
                annotation=use_annotation,
            )
            assert (
                field_info.default == Undefined or field_info.default == RequiredParam
            ), (
                f"`{field_info.__class__.__name__}` default value cannot be set in"
                f" `Annotated` for {param_name!r}. Set the default value with `=` instead."
            )
            if value is not inspect.Signature.empty:
                assert not is_path_param, "Path parameters cannot have default values"
                field_info.default = value
            else:
                field_info.default = RequiredParam
        # Get Annotated Depends
        elif isinstance(fastapi_annotation, params.Depends):
            depends = fastapi_annotation
    # Get Depends from default value
    if isinstance(value, params.Depends):
        assert depends is None, (
            "Cannot specify `Depends` in `Annotated` and default value"
            f" together for {param_name!r}"
        )
        assert field_info is None, (
            "Cannot specify a FastAPI annotation in `Annotated` and `Depends` as a"
            f" default value together for {param_name!r}"
        )
        depends = value
    # Get FieldInfo from default value
    elif isinstance(value, FieldInfo):
        assert field_info is None, (
            "Cannot specify FastAPI annotations in `Annotated` and default value"
            f" together for {param_name!r}"
        )
        field_info = value
        if isinstance(field_info, FieldInfo):
            field_info.annotation = type_annotation

    # Get Depends from type annotation
    if depends is not None and depends.dependency is None:
        # Copy `depends` before mutating it
        depends = copy(depends)
        depends = dataclasses.replace(depends, dependency=type_annotation)

    # Handle non-param type annotations like Request
    # Only apply special handling when there's no explicit Depends - if there's a Depends,
    # the dependency will be called and its return value used instead of the special injection
    if depends is None and lenient_issubclass(
        type_annotation,
        (
            Request,
            WebSocket,
            HTTPConnection,
            Response,
            StarletteBackgroundTasks,
            SecurityScopes,
        ),
    ):
        assert field_info is None, (
            f"Cannot specify FastAPI annotation for type {type_annotation!r}"
        )
    # Handle default assignations, neither field_info nor depends was not found in Annotated nor default value
    elif field_info is None and depends is None:
        default_value = value if value is not inspect.Signature.empty else RequiredParam
        if is_path_param:
            # We might check here that `default_value is RequiredParam`, but the fact is that the same
            # parameter might sometimes be a path parameter and sometimes not. See
            # `tests/test_infer_param_optionality.py` for an example.
            field_info = params.Path(annotation=use_annotation)
        elif is_uploadfile_or_nonable_uploadfile_annotation(
            type_annotation
        ) or is_uploadfile_sequence_annotation(type_annotation):
            field_info = params.File(annotation=use_annotation, default=default_value)
        elif not field_annotation_is_scalar(annotation=type_annotation):
            field_info = params.Body(annotation=use_annotation, default=default_value)
        else:
            field_info = params.Query(annotation=use_annotation, default=default_value)

    field = None
    # It's a field_info, not a dependency
    if field_info is not None:
        # Handle field_info.in_
        if is_path_param:
            assert isinstance(field_info, params.Path), (
                f"Cannot use `{field_info.__class__.__name__}` for path param"
                f" {param_name!r}"
            )
        elif (
            isinstance(field_info, params.Param)
            and getattr(field_info, "in_", None) is None
        ):
            field_info.in_ = params.ParamTypes.query
        use_annotation_from_field_info = use_annotation
        if isinstance(field_info, params.Form):
            ensure_multipart_is_installed()
        if not field_info.alias and getattr(field_info, "convert_underscores", None):
            alias = param_name.replace("_", "-")
        else:
            alias = field_info.alias or param_name
        field_info.alias = alias
        field = create_model_field(
            name=param_name,
            type_=use_annotation_from_field_info,
            default=field_info.default,
            alias=alias,
            field_info=field_info,
        )
        if is_path_param:
            assert is_scalar_field(field=field), (
                "Path params must be of one of the supported types"
            )
        elif isinstance(field_info, params.Query):
            assert (
                is_scalar_field(field)
                or field_annotation_is_scalar_sequence(field.field_info.annotation)
                or lenient_issubclass(field.field_info.annotation, BaseModel)
            ), f"Query parameter {param_name!r} must be one of the supported types"

    return ParamDetails(type_annotation=type_annotation, depends=depends, field=field)


def add_param_to_fields(*, field: ModelField, dependant: Dependant) -> None:
    field_info = field.field_info
    field_info_in = getattr(field_info, "in_", None)
    if field_info_in == params.ParamTypes.path:
        dependant.path_params.append(field)
    elif field_info_in == params.ParamTypes.query:
        dependant.query_params.append(field)
    elif field_info_in == params.ParamTypes.header:
        dependant.header_params.append(field)
    else:
        assert field_info_in == params.ParamTypes.cookie, (
            f"non-body parameters must be in path, query, header or cookie: {field.name}"
        )
        dependant.cookie_params.append(field)


async def _solve_generator(
    *, dependant: Dependant, stack: AsyncExitStack, sub_values: dict[str, Any]
) -> Any:
    assert dependant.call
    if _is_async_gen_callable(dependant.call):
        cm = asynccontextmanager(dependant.call)(**sub_values)
    elif _is_gen_callable(dependant.call):
        cm = contextmanager_in_threadpool(contextmanager(dependant.call)(**sub_values))
    return await stack.enter_async_context(cm)


def dependant_has_generator_dependencies(dependant: Dependant) -> bool:
    return any(
        _is_gen_callable(sub.call)
        or _is_async_gen_callable(sub.call)
        or dependant_has_generator_dependencies(sub)
        for sub in dependant.dependencies
    )


@dataclass
class SolvedDependency:
    values: dict[str, Any]
    errors: list[Any]
    background_tasks: StarletteBackgroundTasks | None
    response: Response | None
    dependency_cache: dict[DependencyCacheKey, Any]


async def solve_dependencies(
    *,
    request: Request | WebSocket,
    dependant: Dependant,
    body: dict[str, Any] | FormData | bytes | None = None,
    background_tasks: StarletteBackgroundTasks | None = None,
    response: Response | None = None,
    dependency_overrides_provider: Any | None = None,
    dependency_cache: dict[DependencyCacheKey, Any] | None = None,
    # TODO: remove this parameter later, no longer used, not removing it yet as some
    # people might be monkey patching this function (although that's not supported)
    async_exit_stack: AsyncExitStack,
    embed_body_fields: bool,
    _uses_scopes_cache: _UsesScopesCache | None = None,
) -> SolvedDependency:
    values: dict[str, Any] = {}
    errors: list[Any] = []
    if response is None and dependant_needs_response(dependant):
        response = Response()
        del response.headers["content-length"]
        response.status_code = None  # type: ignore
    if dependency_cache is None:
        dependency_cache = {}
    overrides = (
        dependency_overrides_provider.dependency_overrides
        if dependency_overrides_provider
        else None
    )
    for sub_dependant in dependant.dependencies:
        call = cast(AnyCallable, sub_dependant.call)
        use_sub_dependant = sub_dependant
        if overrides:
            call = overrides.get(call, call)
            use_path: str = sub_dependant.path  # type: ignore
            use_sub_dependant = get_dependant(
                path=use_path,
                call=call,
                name=sub_dependant.name,
                parent_oauth_scopes=_get_oauth_scopes(dependant=sub_dependant),
                scope=sub_dependant.scope,
            )

        if not overrides and dependant_is_leaf(sub_dependant):
            sub_plan = dependant_param_plan(sub_dependant)
            if sub_plan.specs:
                sub_values, sub_errors = extract_params(
                    sub_plan.specs,
                    request.scope,
                    request.cookies if sub_plan.needs_cookies else None,
                )
                if sub_errors:
                    errors.extend(sub_errors)
                    continue
            else:
                sub_values = {}
        elif not overrides and dependant_is_simple(sub_dependant):
            errors_before = len(errors)
            sub_values = await solve_simple(
                sub_dependant, request, dependency_cache, errors
            )
            if len(errors) != errors_before:
                continue
        else:
            solved_result = await solve_dependencies(
                request=request,
                dependant=use_sub_dependant,
                body=body,
                background_tasks=background_tasks,
                response=response,
                dependency_overrides_provider=dependency_overrides_provider,
                dependency_cache=dependency_cache,
                async_exit_stack=async_exit_stack,
                embed_body_fields=embed_body_fields,
                _uses_scopes_cache=_uses_scopes_cache,
            )
            background_tasks = solved_result.background_tasks
            if solved_result.errors:
                errors.extend(solved_result.errors)
                continue
            sub_values = solved_result.values
        sub_dependant_cache_key = dependant_cache_key(sub_dependant)
        if sub_dependant.use_cache and sub_dependant_cache_key in dependency_cache:
            solved = dependency_cache[sub_dependant_cache_key]
        else:
            is_generator, is_coroutine = dependant_call_kinds(use_sub_dependant)
            if is_generator:
                use_astack = request.scope.get(
                    "fastapi_function_astack"
                    if sub_dependant.scope == "function"
                    else "fastapi_inner_astack"
                )
                if not isinstance(use_astack, AsyncExitStack):
                    raise RuntimeError(
                        "dependency with yield needs an exit stack in the request scope"
                    )
                solved = await _solve_generator(
                    dependant=use_sub_dependant,
                    stack=use_astack,
                    sub_values=sub_values,
                )
            elif is_coroutine:
                solved = await call(**sub_values)
            else:
                solved = await run_in_threadpool(call, **sub_values)
        if sub_dependant.name is not None:
            values[sub_dependant.name] = solved
        if sub_dependant_cache_key not in dependency_cache:
            dependency_cache[sub_dependant_cache_key] = solved
    plan = dependant_param_plan(dependant)
    if plan.specs:
        param_values, param_errors = extract_params(
            plan.specs,
            request.scope,
            request.cookies if plan.needs_cookies else None,
        )
        values.update(param_values)
        errors.extend(param_errors)
    if dependant.body_params:
        (
            body_values,
            body_errors,
        ) = await request_body_to_args(  # body_params checked above
            body_fields=dependant.body_params,
            received_body=body,
            embed_body_fields=embed_body_fields,
        )
        values.update(body_values)
        errors.extend(body_errors)
    if dependant.http_connection_param_name:
        values[dependant.http_connection_param_name] = request
    if dependant.request_param_name and isinstance(request, Request):
        values[dependant.request_param_name] = request
    elif dependant.websocket_param_name and isinstance(request, WebSocket):
        values[dependant.websocket_param_name] = request
    if dependant.background_tasks_param_name:
        if background_tasks is None:
            background_tasks = BackgroundTasks()
        values[dependant.background_tasks_param_name] = background_tasks
    if dependant.response_param_name:
        values[dependant.response_param_name] = response
    if dependant.security_scopes_param_name:
        values[dependant.security_scopes_param_name] = SecurityScopes(
            scopes=_get_oauth_scopes(dependant=dependant)
        )
    return SolvedDependency(
        values=values,
        errors=errors,
        background_tasks=background_tasks,
        response=response,
        dependency_cache=dependency_cache,
    )


async def solve_simple(
    dependant: Dependant,
    request: Request | WebSocket,
    dependency_cache: dict[DependencyCacheKey, Any],
    errors: list[Any],
) -> dict[str, Any]:
    """solve_dependencies for a simple subtree (see dependant_is_simple) with no overrides.

    Same sub-dependant order, cache key and use_cache rules, generator handling and error
    order: a sub-dependant's errors are appended before its own parameter errors, and a
    sub-dependant with errors is not called. Returns the values for dependant.call.
    """
    values: dict[str, Any] = {}
    for sub_dependant in dependant.dependencies:
        if dependant_is_leaf(sub_dependant):
            sub_plan = dependant_param_plan(sub_dependant)
            if sub_plan.specs:
                sub_values, sub_errors = extract_params(
                    sub_plan.specs,
                    request.scope,
                    request.cookies if sub_plan.needs_cookies else None,
                )
                if sub_errors:
                    errors.extend(sub_errors)
                    continue
            else:
                sub_values = {}
        else:
            errors_before = len(errors)
            sub_values = await solve_simple(
                sub_dependant, request, dependency_cache, errors
            )
            if len(errors) != errors_before:
                continue
        sub_dependant_cache_key = dependant_cache_key(sub_dependant)
        if sub_dependant.use_cache and sub_dependant_cache_key in dependency_cache:
            solved = dependency_cache[sub_dependant_cache_key]
        else:
            call = cast(AnyCallable, sub_dependant.call)
            is_generator, is_coroutine = dependant_call_kinds(sub_dependant)
            if is_generator:
                use_astack = request.scope.get(
                    "fastapi_function_astack"
                    if sub_dependant.scope == "function"
                    else "fastapi_inner_astack"
                )
                if not isinstance(use_astack, AsyncExitStack):
                    raise RuntimeError(
                        "dependency with yield needs an exit stack in the request scope"
                    )
                solved = await _solve_generator(
                    dependant=sub_dependant, stack=use_astack, sub_values=sub_values
                )
            elif is_coroutine:
                solved = await call(**sub_values)
            else:
                solved = await run_in_threadpool(call, **sub_values)
        if sub_dependant.name is not None:
            values[sub_dependant.name] = solved
        if sub_dependant_cache_key not in dependency_cache:
            dependency_cache[sub_dependant_cache_key] = solved
    plan = dependant_param_plan(dependant)
    if plan.specs:
        param_values, param_errors = extract_params(
            plan.specs,
            request.scope,
            request.cookies if plan.needs_cookies else None,
        )
        values.update(param_values)
        errors.extend(param_errors)
    return values


def _validate_value_with_model_field(
    *, field: ModelField, value: Any, values: dict[str, Any], loc: tuple[str, ...]
) -> tuple[Any, list[Any]]:
    if value is None:
        if field.required:
            return None, [get_missing_field_error(loc=loc)]
        else:
            return field_default_value(field), []
    return field.validate(value, values, loc=loc)


def _get_multidict_value(
    field: ModelField, values: Mapping[str, Any], alias: str | None = None
) -> Any:
    alias = alias or field.alias_for_validation
    if (
        field.is_sequence
        and not field.is_json
        and isinstance(values, (ImmutableMultiDict, Headers))
    ):
        value = values.getlist(alias)
    else:
        value = values.get(alias, None)
    if (
        value is None
        or (field.is_sequence and len(value) == 0)
        or (
            isinstance(value, str)
            and not value
            and isinstance(field.field_info, params.Form)
        )
    ):
        if field.required:
            return None
        return field_default_value(field)
    return value


def request_params_to_model_arg(
    field: ModelField,
    received_params: Mapping[str, Any] | QueryParams | Headers,
) -> tuple[dict[str, Any], list[Any]]:
    fields_to_extract = get_cached_model_fields(field.field_info.annotation)
    # If headers are in a Pydantic model, the way to disable convert_underscores
    # would be with Header(convert_underscores=False) at the Pydantic model level
    default_convert_underscores = getattr(field.field_info, "convert_underscores", True)

    params_to_process: dict[str, Any] = {}
    processed_keys = set()

    for sub_field in fields_to_extract:
        alias = None
        if isinstance(received_params, Headers):
            # Handle fields extracted from a Pydantic Model for a header, each field
            # doesn't have a FieldInfo of type Header with the default convert_underscores=True
            convert_underscores = getattr(
                sub_field.field_info, "convert_underscores", default_convert_underscores
            )
            if convert_underscores:
                alias = get_validation_alias(sub_field)
                if alias == sub_field.name:
                    alias = alias.replace("_", "-")
        value = _get_multidict_value(sub_field, received_params, alias=alias)
        if value is not None:
            params_to_process[get_validation_alias(sub_field)] = value
        processed_keys.add(alias or get_validation_alias(sub_field))
        # For headers with convert_underscores=True, mark both the converted
        # header name and the original field alias as processed to avoid
        # accepting the original alias as an extra header.
        processed_keys.add(get_validation_alias(sub_field))

    for key in received_params.keys():
        if key not in processed_keys:
            if isinstance(received_params, (ImmutableMultiDict, Headers)):
                value = received_params.getlist(key)
                if isinstance(value, list) and (len(value) == 1):
                    params_to_process[key] = value[0]
                else:
                    params_to_process[key] = value
            else:
                params_to_process[key] = received_params.get(key)

    field_info = field.field_info
    assert isinstance(field_info, params.Param), "Params must be subclasses of Param"
    loc: tuple[str, ...] = (field_info.in_.value,)
    v_, errors_ = _validate_value_with_model_field(
        field=field, value=params_to_process, values={}, loc=loc
    )
    return {field.name: v_}, errors_


ParamEntry = tuple[str, str, str, bool, bool, bool, bool, ModelField, Any]
"""(name, alias, location, multi, is_sequence, required, is_model, field, lookup): one path,
query, header or cookie parameter. multi: collect every value (a sequence field on a multidict
source); is_model: the location's single pydantic-model field, extracted with
request_params_to_model_arg; lookup: the alias as the raw scope stores it (latin-1 lower-case
bytes for headers, the alias itself otherwise).
"""

QUERY_ITEMS_KEY = "notslowapi.query_items"


@dataclass(frozen=True, slots=True)
class ParamPlan:
    """A dependant's parameter specs in the solver's order and the request sources they read."""

    specs: tuple[ParamEntry, ...]
    needs_path: bool
    needs_query: bool
    needs_headers: bool
    needs_cookies: bool


def json_marked(field: ModelField) -> bool:
    from pydantic import Json

    return any(type(item) is Json for item in field.field_info.metadata)


def compile_param_plan(dependant: Dependant) -> ParamPlan:
    """One spec per path, query, header and cookie parameter, in the order the solver read them."""
    specs: list[ParamEntry] = []
    for fields, location, multidict in (
        (dependant.path_params, "path", False),
        (dependant.query_params, "query", True),
        (dependant.header_params, "header", True),
        (dependant.cookie_params, "cookie", False),
    ):
        if len(fields) == 1 and fields[0].is_model:
            field = fields[0]
            specs.append(
                (
                    field.name,
                    field.alias_for_validation,
                    location,
                    False,
                    False,
                    False,
                    True,
                    field,
                    None,
                )
            )
            continue
        for field in fields:
            multi = multidict and field.is_sequence and not json_marked(field)
            alias = field.alias_for_validation
            specs.append(
                (
                    field.name,
                    alias,
                    field.param_location or location,
                    multi,
                    field.is_sequence,
                    field.field_info.is_required(),
                    False,
                    field,
                    alias.lower().encode("latin-1") if location == "header" else alias,
                )
            )
    return ParamPlan(
        tuple(specs),
        bool(dependant.path_params),
        bool(dependant.query_params),
        bool(dependant.header_params),
        bool(dependant.cookie_params),
    )


def dependant_param_plan(dependant: Dependant) -> ParamPlan:
    """compile_param_plan computed once per Dependant."""
    plan = dependant.param_plan
    if plan is None:
        plan = dependant.param_plan = compile_param_plan(dependant)
    return plan


def compile_param_specs(dependant: Dependant) -> tuple[ParamEntry, ...] | None:
    """Specs for a dependant whose parameters are only plain path and query params.

    None when anything else takes part (dependencies, body, header or cookie params,
    request/response/background/security params, a pydantic model as query params) so the
    caller keeps solve_dependencies.
    """
    if (
        dependant.dependencies
        or dependant.body_params
        or dependant.header_params
        or dependant.cookie_params
        or dependant.request_param_name
        or dependant.http_connection_param_name
        or dependant.websocket_param_name
        or dependant.response_param_name
        or dependant.background_tasks_param_name
        or dependant.security_scopes_param_name
    ):
        return None
    plan = dependant_param_plan(dependant)
    if any(spec[6] for spec in plan.specs):
        return None
    return plan.specs


def field_default_value(field: ModelField) -> Any:
    """deepcopy(field.default) for an optional field, without FieldInfo.get_default when there is no factory."""
    field_info = field.field_info
    if field_info.default_factory is None:
        return deepcopy(field_info.default)
    return deepcopy(field.default)


def query_items(scope: Mapping[str, Any]) -> list[tuple[str, str]]:
    """The parsed query string, parsed once per request and kept in the scope."""
    items = scope.get(QUERY_ITEMS_KEY)
    if items is None:
        items = parse_query_string(scope["query_string"].decode("latin-1"))
        scope[QUERY_ITEMS_KEY] = items  # type: ignore[index]
    return items


def extract_params(
    specs: tuple[ParamEntry, ...],
    scope: Mapping[str, Any],
    cookies: Mapping[str, str] | None = None,
) -> tuple[dict[str, Any], list[Any]]:
    """request_params_to_args for compiled specs, reading the ASGI scope directly.

    Path params come from scope["path_params"], query values from the query string parsed
    once per request (last value wins, every value for a multi spec, as QueryParams does),
    header values from the raw header list (first match, or every match for a multi spec,
    as Headers does). Model-typed params still get the real QueryParams or Headers object.
    """
    values: dict[str, Any] = {}
    errors: list[Any] = []
    path_params: Mapping[str, Any] | None = None
    query_map: dict[str, str] | None = None
    for (
        name,
        alias,
        location,
        multi,
        is_sequence,
        required,
        is_model,
        field,
        lookup,
    ) in specs:
        if is_model:
            if location == "path":
                source: Any = scope.get("path_params") or {}
            elif location == "query":
                source = QueryParams.from_query_string(scope["query_string"])
            elif location == "header":
                source = Headers(scope=scope)  # type: ignore[arg-type]
            else:
                source = cookies if cookies is not None else {}
            model_values, model_errors = request_params_to_model_arg(field, source)
            values.update(model_values)
            errors.extend(model_errors)
            continue
        if location == "path":
            if path_params is None:
                path_params = scope.get("path_params") or {}
            value: Any = path_params.get(alias)
        elif location == "query":
            if multi:
                value = [
                    item_value
                    for item_key, item_value in query_items(scope)
                    if item_key == alias
                ]
            else:
                if query_map is None:
                    query_map = dict(query_items(scope))
                value = query_map.get(alias)
        elif location == "header":
            if multi:
                value = [
                    header_value.decode("latin-1")
                    for header_key, header_value in scope["headers"]
                    if header_key == lookup
                ]
            else:
                value = None
                for header_key, header_value in scope["headers"]:
                    if header_key == lookup:
                        value = header_value.decode("latin-1")
                        break
        else:
            value = cookies.get(alias) if cookies is not None else None
        if value is None or (is_sequence and len(value) == 0):
            if required:
                errors.append(get_missing_field_error(loc=(location, alias)))
                continue
            value = field_default_value(field)
            if value is None:
                values[name] = None
                continue
        v_, errors_ = field.validate(value, values, loc=(location, alias))
        if errors_:
            errors.extend(errors_)
        else:
            values[name] = v_
    return values, errors


def request_params_to_args(
    fields: Sequence[ModelField],
    received_params: Mapping[str, Any] | QueryParams | Headers,
) -> tuple[dict[str, Any], list[Any]]:
    values: dict[str, Any] = {}
    errors: list[dict[str, Any]] = []

    if not fields:
        return values, errors

    first_field = fields[0]
    if len(fields) == 1 and first_field.is_model:
        return request_params_to_model_arg(first_field, received_params)

    for field in fields:
        alias = field.alias_for_validation
        value = _get_multidict_value(field, received_params, alias=alias)
        location = field.param_location
        if location is None:
            raise TypeError("Params must be subclasses of Param")
        loc = (location, alias)
        if value is None:
            if field.required:
                errors.append(get_missing_field_error(loc=loc))
            else:
                values[field.name] = deepcopy(field.default)
            continue
        v_, errors_ = field.validate(value, values, loc=loc)
        if errors_:
            errors.extend(errors_)
        else:
            values[field.name] = v_
    return values, errors


def is_union_of_base_models(field_type: Any) -> bool:
    """Check if field type is a Union where all members are BaseModel subclasses."""
    from notslowapi.types import UnionType

    origin = get_origin(field_type)

    # Check if it's a Union type (covers both typing.Union and types.UnionType in Python 3.10+)
    if origin is not Union and origin is not UnionType:
        return False

    union_args = get_args(field_type)

    for arg in union_args:
        if not lenient_issubclass(arg, BaseModel):
            return False

    return True


def _should_embed_body_fields(fields: list[ModelField]) -> bool:
    if not fields:
        return False
    # More than one dependency could have the same field, it would show up as multiple
    # fields but it's the same one, so count them by name
    body_param_names_set = {field.name for field in fields}
    # A top level field has to be a single field, not multiple
    if len(body_param_names_set) > 1:
        return True
    first_field = fields[0]
    # If it explicitly specifies it is embedded, it has to be embedded
    if getattr(first_field.field_info, "embed", None):
        return True
    # If it's a Form (or File) field, it has to be a BaseModel (or a union of BaseModels) to be top level
    # otherwise it has to be embedded, so that the key value pair can be extracted
    if (
        isinstance(first_field.field_info, params.Form)
        and not lenient_issubclass(first_field.field_info.annotation, BaseModel)
        and not is_union_of_base_models(first_field.field_info.annotation)
    ):
        return True
    return False


async def _extract_form_body(
    body_fields: list[ModelField],
    received_body: FormData,
) -> dict[str, Any]:
    values = {}

    for field in body_fields:
        value = _get_multidict_value(field, received_body)
        field_info = field.field_info
        if (
            isinstance(field_info, params.File)
            and is_bytes_or_nonable_bytes_annotation(field.field_info.annotation)
            and isinstance(value, UploadFile)
        ):
            value = await value.read()
        elif (
            is_bytes_sequence_annotation(field.field_info.annotation)
            and isinstance(field_info, params.File)
            and value_is_sequence(value)
        ):
            # For types
            assert isinstance(value, sequence_types)
            results: list[bytes | str] = []
            for sub_value in value:
                results.append(await sub_value.read())
            value = serialize_sequence_value(field=field, value=results)
        if value is not None:
            values[get_validation_alias(field)] = value
    field_aliases = {get_validation_alias(field) for field in body_fields}
    for key in received_body.keys():
        if key not in field_aliases:
            param_values = received_body.getlist(key)
            if len(param_values) == 1:
                values[key] = param_values[0]
            else:
                values[key] = param_values
    return values


async def request_body_to_args(
    body_fields: list[ModelField],
    received_body: dict[str, Any] | FormData | bytes | None,
    embed_body_fields: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    values: dict[str, Any] = {}
    errors: list[dict[str, Any]] = []
    assert body_fields, "request_body_to_args() should be called with fields"
    single_not_embedded_field = len(body_fields) == 1 and not embed_body_fields
    first_field = body_fields[0]
    body_to_process = received_body

    fields_to_extract: list[ModelField] = body_fields

    if (
        single_not_embedded_field
        and lenient_issubclass(first_field.field_info.annotation, BaseModel)
        and isinstance(received_body, FormData)
    ):
        fields_to_extract = get_cached_model_fields(first_field.field_info.annotation)

    if isinstance(received_body, FormData):
        body_to_process = await _extract_form_body(fields_to_extract, received_body)

    if single_not_embedded_field:
        loc: tuple[str, ...] = ("body",)
        v_, errors_ = _validate_value_with_model_field(
            field=first_field, value=body_to_process, values=values, loc=loc
        )
        return {first_field.name: v_}, errors_
    for field in body_fields:
        loc = ("body", get_validation_alias(field))
        value: Any | None = None
        if body_to_process is not None and not isinstance(body_to_process, bytes):
            try:
                value = body_to_process.get(get_validation_alias(field))
            # If the received body is a list, not a dict
            except AttributeError:
                errors.append(get_missing_field_error(loc))
                continue
        v_, errors_ = _validate_value_with_model_field(
            field=field, value=value, values=values, loc=loc
        )
        if errors_:
            errors.extend(errors_)
        else:
            values[field.name] = v_
    return values, errors


def _get_body_field(
    *, body_params: list[ModelField], name: str, embed_body_fields: bool
) -> ModelField | None:
    """
    Get a ModelField representing the request body for a path operation, combining
    all body parameters into a single field if necessary.

    Used to check if it's form data (with `isinstance(body_field, params.Form)`)
    or JSON and to generate the JSON Schema for a request body.

    This is **not** used to validate/parse the request body, that's done with each
    individual body parameter.
    """
    if not body_params:
        return None
    first_param = body_params[0]
    if not embed_body_fields:
        return first_param
    model_name = "Body_" + name
    BodyModel = create_body_model(fields=body_params, model_name=model_name)
    required = any(True for f in body_params if f.field_info.is_required())
    BodyFieldInfo_kwargs: dict[str, Any] = {
        "annotation": BodyModel,
        "alias": "body",
    }
    if not required:
        BodyFieldInfo_kwargs["default"] = None
    if any(isinstance(f.field_info, params.File) for f in body_params):
        BodyFieldInfo: type[params.Body] = params.File
    elif any(isinstance(f.field_info, params.Form) for f in body_params):
        BodyFieldInfo = params.Form
    else:
        BodyFieldInfo = params.Body

        body_param_media_types = [
            f.field_info.media_type
            for f in body_params
            if isinstance(f.field_info, params.Body)
        ]
        if len(set(body_param_media_types)) == 1:
            BodyFieldInfo_kwargs["media_type"] = body_param_media_types[0]
    final_field = create_model_field(
        name="body",
        type_=BodyModel,
        alias="body",
        field_info=BodyFieldInfo(**BodyFieldInfo_kwargs),
    )
    return final_field


def get_validation_alias(field: ModelField) -> str:
    return field.alias_for_validation

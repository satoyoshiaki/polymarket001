"""Minimal local pydantic compatibility shim for offline test execution."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import MISSING
from enum import Enum
from typing import Any, get_args, get_origin


class _FieldInfo:
    def __init__(self, default: Any = MISSING, default_factory: Any = MISSING) -> None:
        self.default = default
        self.default_factory = default_factory


def Field(default: Any = MISSING, *, default_factory: Any = MISSING) -> _FieldInfo:
    return _FieldInfo(default=default, default_factory=default_factory)


def ConfigDict(**kwargs: Any) -> dict[str, Any]:
    return dict(kwargs)


class SecretStr(str):
    def get_secret_value(self) -> str:
        return str(self)


def model_validator(*, mode: str) -> Any:
    def decorator(func: Any) -> Any:
        func.__pydantic_validator_mode__ = mode
        return func

    return decorator


class BaseModel:
    model_config: dict[str, Any] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        validators: list[Any] = []
        for name in dir(cls):
            value = getattr(cls, name)
            if callable(value) and getattr(value, "__pydantic_validator_mode__", None) == "after":
                validators.append(value)
        cls.__pydantic_after_validators__ = validators

    def __init__(self, **kwargs: Any) -> None:
        annotations = self._merged_annotations()
        extra = set(kwargs) - set(annotations)
        if extra and self.model_config.get("extra") == "forbid":
            raise TypeError(f"Unexpected fields: {sorted(extra)}")

        for name, annotation in annotations.items():
            if name in kwargs:
                value = kwargs[name]
            else:
                value = self._default_for_field(name)
            setattr(self, name, self._coerce_value(annotation, value))

        for validator in getattr(self.__class__, "__pydantic_after_validators__", []):
            validator(self)

    @classmethod
    def model_validate(cls, data: dict[str, Any]) -> "BaseModel":
        return cls(**data)

    def model_dump(self, mode: str | None = None) -> dict[str, Any]:
        return {name: self._dump_value(getattr(self, name), mode=mode) for name in self._merged_annotations()}

    @classmethod
    def _merged_annotations(cls) -> dict[str, Any]:
        annotations: dict[str, Any] = {}
        for base in reversed(cls.__mro__):
            annotations.update(getattr(base, "__annotations__", {}))
        return annotations

    @classmethod
    def _default_for_field(cls, name: str) -> Any:
        if not hasattr(cls, name):
            raise TypeError(f"Missing required field: {name}")
        default = getattr(cls, name)
        if isinstance(default, _FieldInfo):
            if default.default_factory is not MISSING:
                return default.default_factory()
            if default.default is not MISSING:
                return deepcopy(default.default)
            raise TypeError(f"Missing required field: {name}")
        return deepcopy(default)

    @classmethod
    def _coerce_value(cls, annotation: Any, value: Any) -> Any:
        if value is None:
            return None

        origin = get_origin(annotation)
        args = get_args(annotation)

        if origin is None:
            if isinstance(annotation, type):
                if issubclass(annotation, BaseModel):
                    if isinstance(value, annotation):
                        return value
                    if isinstance(value, dict):
                        return annotation(**value)
                if issubclass(annotation, Enum):
                    if isinstance(value, annotation):
                        return value
                    return annotation(value)
                if annotation is SecretStr:
                    return SecretStr(value)
            return value

        if origin in (list, list[Any]):
            subtype = args[0] if args else Any
            return [cls._coerce_value(subtype, item) for item in value]

        if origin in (dict, dict[Any, Any]):
            key_type = args[0] if len(args) > 0 else Any
            val_type = args[1] if len(args) > 1 else Any
            return {
                cls._coerce_value(key_type, key): cls._coerce_value(val_type, item)
                for key, item in value.items()
            }

        if origin in (tuple,):
            subtypes = args or ()
            return tuple(
                cls._coerce_value(subtypes[min(i, len(subtypes) - 1)], item) if subtypes else item
                for i, item in enumerate(value)
            )

        if origin is not None and type(None) in args:
            non_none = [arg for arg in args if arg is not type(None)]
            subtype = non_none[0] if non_none else Any
            return cls._coerce_value(subtype, value)

        return value

    @classmethod
    def _dump_value(cls, value: Any, mode: str | None = None) -> Any:
        if isinstance(value, BaseModel):
            return value.model_dump(mode=mode)
        if isinstance(value, list):
            return [cls._dump_value(item, mode=mode) for item in value]
        if isinstance(value, dict):
            return {key: cls._dump_value(item, mode=mode) for key, item in value.items()}
        if isinstance(value, SecretStr):
            return str(value)
        if isinstance(value, Enum):
            return value.value if mode == "json" else value
        return value

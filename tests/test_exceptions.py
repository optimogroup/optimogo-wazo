from wazo_dird_optimogo.exceptions import (
    OptimoGoError, OptimoGoAuthError, OptimoGoTimeout,
    OptimoGoUnavailable, OptimoGoLookupError,
)


def test_all_errors_subclass_base():
    for cls in (OptimoGoAuthError, OptimoGoTimeout, OptimoGoUnavailable, OptimoGoLookupError):
        assert issubclass(cls, OptimoGoError)


def test_base_is_exception():
    assert issubclass(OptimoGoError, Exception)

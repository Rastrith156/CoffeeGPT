from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from core.errors import PlatformError, APIError, ValidationError, AuthenticationError, AuthorizationError
from core.logger import logger

async def platform_error_handler(request: Request, exc: PlatformError):
    logger.error("PlatformError occurred: {} - Context: {}", exc.message, exc.context)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.message, "context": exc.context},
    )

async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.warning("Validation error on request path {}: {}", request.url.path, exc.errors())
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"error": "Data validation failed", "details": exc.errors()},
    )

async def generic_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled generic exception: {}", str(exc))
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": "An unexpected system error occurred."},
    )

def register_error_handlers(app):
    app.add_exception_handler(PlatformError, platform_error_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)

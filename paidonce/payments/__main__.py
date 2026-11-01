import uvicorn

from paidonce import config, tls
from paidonce.payments.service import app

if __name__ == "__main__":
    uvicorn.run(
        app, host="127.0.0.1", port=config.PAYMENTS_PORT, log_level="warning", **tls.server_ssl_kwargs("payments")
    )

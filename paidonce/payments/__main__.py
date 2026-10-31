import uvicorn

from paidonce import config
from paidonce.payments.service import app

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=config.PAYMENTS_PORT, log_level="warning")

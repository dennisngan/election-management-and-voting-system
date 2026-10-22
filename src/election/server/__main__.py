import uvicorn

from election.server.app import create_app
from election.server.config import Settings


def main() -> None:
    settings = Settings()
    uvicorn.run(
        create_app(),
        host=settings.host,
        port=settings.port,
        ssl_certfile=settings.tls_cert,
        ssl_keyfile=settings.tls_key,
    )


if __name__ == "__main__":
    main()

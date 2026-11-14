# Local development with MySQL

1. Install Docker Desktop and `uv`.
2. Copy `.env.example` to `.env`. Set `MYSQL_PASSWORD` and `MYSQL_ROOT_PASSWORD` to different local-only values. `.env` is ignored by Git and excluded from Docker images.
3. Start the database, wait for its health check, and run schema migrations explicitly:

   ```powershell
   docker compose up -d mysql
   docker compose ps
   docker compose run --rm app uv run --no-sync manage.py migrate
   ```

4. Start the app and create a broker account:

   ```powershell
   docker compose up --build -d app
   docker compose run --rm app uv run --no-sync manage.py createsuperuser
   ```

5. Open <http://127.0.0.1:8000/> and sign in.
6. Stop the containers without deleting local data:

   ```powershell
   docker compose down
   ```

The `propertypost_mysql_data` named volume persists across container restarts and `docker compose down`. Do not pass `--volumes` or `-v` if the local database should be retained. To inspect health, run `docker compose ps` and `docker compose logs app mysql` (database logs may contain operational details; never enable query/password logging).

## Database separation

Compose sets the app's MySQL host to the internal `mysql` service. Production settings require a different Hostinger hostname, database, username and password. Store the production values in Google Secret Manager and inject them into Cloud Run. Never copy production credentials into local `.env`, GitHub, Docker build arguments or the image. Enable TLS in production; configure a trusted CA path if Hostinger requires a custom CA.

No production database connection or schema migration is made by these local commands. Apply production migrations only as a reviewed, explicit release operation after a backup is available.

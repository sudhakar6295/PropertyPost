# Database configuration

PropertyPost uses MySQL 8 for both environments. Local development connects to the MySQL Compose service and stores data on the `propertypost_mysql_data` named volume. Production uses the independent Hostinger MySQL instance over TLS. The application selects the connection through `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_DATABASE`, `MYSQL_USER`, and `MYSQL_PASSWORD`; production values are injected from Google Secret Manager.

Django models and migrations remain the schema source of truth. Public plot information and owner/negotiation information are separate models and tables. The web and API layers use Django ORM repositories and transactions. There is no document database adapter.

Local setup and operational commands are in [mysql-setup.md](mysql-setup.md). Never run production migration commands automatically at container startup. Before manually migrating Hostinger, take a backup and verify the production environment variables without printing credential values.

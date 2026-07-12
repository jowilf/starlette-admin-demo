#!/bin/bash
set -euo pipefail

mysql -u root -p"${MYSQL_ROOT_PASSWORD}" <<-EOSQL
    CREATE DATABASE IF NOT EXISTS umami;
    CREATE USER IF NOT EXISTS 'umami'@'%' IDENTIFIED BY '${UMAMI_DB_PASSWORD}';
    GRANT ALL PRIVILEGES ON umami.* TO 'umami'@'%';
    FLUSH PRIVILEGES;
EOSQL

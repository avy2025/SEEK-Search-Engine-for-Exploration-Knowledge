---
title: Databases
---
# Databases

A database stores and retrieves structured information. Relational databases
organize records into tables with schemas, keys, and constraints. SQL queries
filter, join, and aggregate that information. PostgreSQL is an open-source
relational database with transactions, indexes, and JSON support.

Applications should keep database credentials outside source code and use
parameterized queries. Connection pooling limits resource use, while backups and
tested restore procedures protect persistent data. A database index can speed
up searches but adds work to writes and consumes storage.

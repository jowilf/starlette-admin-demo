Starlette-Admin Demo Application
==========================

This project is the official [Starlette-Admin][1] Demo application that showcases the
main features of *Starlette-Admin*

Available online [here][2]


Usage
-----

The easiest way to run this project is with Docker Compose.

### 1. Prerequisites

Before you begin, make sure you have [Docker](https://docs.docker.com/get-docker/) and the Docker Compose plugin installed.

### 2. Clone the repository

```shell
git clone https://github.com/jowilf/starlette-admin-demo.git
cd starlette-admin-demo
```

### 3. Start the application

```shell
docker compose up -d
```

This will build the image and start the application together with its PostgreSQL and Redis
dependencies, as well as the Celery worker, beat scheduler, and Flower.

Then access the application in your browser at <http://localhost:8000>.

To stop the application:

```shell
docker compose down
```

### Running without Docker

If you prefer to run the project locally instead:

1. Install [Python 3](https://www.python.org/downloads/) and [uv](https://docs.astral.sh/uv/).
2. Create and activate a virtual environment:

   ```shell
   uv venv --python 3.12
   ```

3. Sync dependencies:

   ```shell
   uv sync
   ```

4. Create mock data:

   ```shell
   uv run seed
   ```

5. Run the application:

   ```shell
   uv run -- fastapi dev src/starlette_admin_demo/app.py
   ```

   Then access the application in your browser at the given URL (<https://localhost:8000> by default).


[1]: https://github.com/jowilf/starlette-admin/

[2]: https://starlette-admin-demo.jowilf.com/

Starlette-Admin Demo Application
==========================

This project is the official [Starlette-Admin][1] Demo application that showcases the
main features of *Starlette-Admin*

Available online [here][2]


Usage
-----

To run this project:

1. Prerequisites

Before you begin, make sure you have the following prerequisites installed:

- [Python 3](https://www.python.org/downloads/)
- [uv](https://docs.astral.sh/uv/)
- [MongoDB](https://www.mongodb.com/)

2. Clone the repository:

```shell
git clone https://github.com/jowilf/starlette-admin-demo.git
cd starlette-admin-demo
```

2. Create and activate a virtual environment:

```shell
uv venv --python 3.12
```

3. Sync dependencies:

```shell
uv sync
```

5. Run the application:

```shell
uv run -- uvicorn app.main:app --reload
```

Then access the application in your browser at the given URL (<https://localhost:8000> by default).


[1]: https://github.com/jowilf/starlette-admin/

[2]: https://starlette-admin-demo.jowilf.com/

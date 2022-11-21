Starlette-Admin Demo Application
==========================

This project is the official [Starlette-Admin][1] Demo application that showcases the
main features of *Starlette-Admin*

Available online [here](https://starlette-admin-demo.jowilf.com/)

Usage
-----

To run this project:


1. Clone the repository:
```shell
git clone https://github.com/jowilf/starlette-admin-demo.git
cd starlette-admin-demo
```

2. Install requirements:
```shell
poetry install
```

4. Create and Fill database:
```shell
poetry run python seed.py
```


3. Run the application:
```shell
uvicorn app.main:app
```


Then access the application in your browser at the given URL (<https://localhost:8000> by default).


[1]: https://github.com/jowilf/starlette-admin-demo.git
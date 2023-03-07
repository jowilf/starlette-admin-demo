Starlette-Admin Demo Application
==========================

This project is the official [Starlette-Admin][1] Demo application that showcases the
main features of *Starlette-Admin*

Available online [here][2]

Usage
-----

To run this project:

1. Clone the repository:

```shell
git clone https://github.com/jowilf/starlette-admin-demo.git
cd starlette-admin-demo
```

2. Create and activate a virtual environment:

```shell
python3 -m venv env
source env/bin/activate
```

3. Install requirements:

```shell
pip install -r 'requirements.txt'
```

4. Create and Fill database:

```shell
python seed.py
```

5. Run the application:

```shell
uvicorn app.main:app
```

Then access the application in your browser at the given URL (<https://localhost:8000> by default).


[1]: https://github.com/jowilf/starlette-admin/
[2]: https://starlette-admin-demo.jowilf.com/
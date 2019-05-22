FROM tiangolo/uvicorn-gunicorn-fastapi:python3.7

# Put first so anytime this file changes other cached layers are invalidated.
COPY ./requirements.txt /requirements.txt

# Install dependencies then delete various caches.
RUN pip install -r /requirements.txt && \
  rm -Rf /root/.cache && rm -Rf /tmp/pip-install*

ENV SQLITE_PATH /opt/gitstars.sqlite3

# Finally, copy app.
COPY ./app /app

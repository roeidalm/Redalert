FROM python:3.12-alpine

RUN rm -rf /var/cache/apk/*

#install python dependencies from requirements.txt
COPY requirements.txt /opt/redalert/
RUN pip install -r /opt/redalert/requirements.txt --no-cache-dir

ENV PYTHONIOENCODING=utf-8

ENV LANG=C.UTF-8

COPY redalert.py /opt/redalert

ENTRYPOINT ["python", "/opt/redalert/redalert.py"]

FROM ubuntu:16.04
RUN apt update && apt-get install -y python-pip
RUN pip install --no-cache-dir python-telegram-bot
COPY setup.sh /setup.sh
COPY send.py /send.py
RUN chmod a+x /setup.sh /send.py
CMD ["echo",  "Plz use setup.sh and send.sh"]

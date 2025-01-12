FROM ubuntu:20.04
RUN sed -i 's/archive.ubuntu.com/de.archive.ubuntu.com/g' /etc/apt/sources.list
CMD [ "bash", "/root/launch.sh" ]
RUN apt update && DEBIAN_FRONTEND="noninteractive" apt install -y --no-install-recommends \
    nginx \
    procps \
    python3-pip \
    python3 \
    python3-setuptools \
    ssh \
    apt-transport-https \
    ca-certificates \
    curl \
    gnupg-agent \
    software-properties-common \
    python3.8-dev \
    libpq-dev \
    python3.8 \
    python3-pip \
    build-essential \
    git \
    rsh-client
RUN curl -fsSL https://download.docker.com/linux/ubuntu/gpg | apt-key add -
RUN add-apt-repository "deb [arch=$(dpkg --print-architecture)] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable"
RUN apt-get update && apt-get install -y docker-ce docker-ce-cli containerd.io
RUN pip install pip --upgrade 
# RUN pip install webssh
COPY webssh /root/webssh
RUN pip install -e /root/webssh

RUN docker --version

ADD launch.sh /root
RUN chmod a+x /root/launch.sh

RUN echo "root:odoo" | chpasswd root

COPY requirements.txt .
RUN pip3 install -r requirements.txt


RUN sed -i 's/\#PermitRootLogin\ prohibit-password/PermitRootLogin yes/g' /etc/ssh/sshd_config 
RUN cat /etc/ssh/sshd_config |grep Permit
EXPOSE 8080

RUN touch /tmp/iam_webssh

RUN find /usr/local/lib -name webssh
COPY ["font/Meslo LG M Regular for Powerline.ttf", "/usr/local/lib/python3.8/dist-packages/webssh/static/css/fonts"]
#COPY ["font/Lucida Regular.ttf", "/usr/local/lib/python3.8/dist-packages/webssh/static/css/fonts"]

ADD programs/* /root/programs/
RUN mkdir /root/.ssh
ADD sshkey/* /root/.ssh/
RUN chmod 500 /root/.ssh && \
chmod 400 /root/.ssh/* && \
echo 'Adding paths to .bash_profile' && \
echo 'readonly PATH=$HOME/programs' >> /root/.bash_profile && \ 
echo 'export PATH' >> /root/.bash_profile && \
chmod a+x /root/programs/*  && \
chsh -s /usr/bin/rbash && \
ln -s /usr/bin/ssh /root/programs/ssh

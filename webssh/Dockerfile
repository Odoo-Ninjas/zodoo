FROM ubuntu:24.04
ARG  APT_PROXY_IP
ARG  APT_OPTIONS
CMD [ "bash", "/root/launch.sh" ]

#___SNIPPET_APT_MIRRORS___
#___SNIPPET_APT_PROXY___
RUN DEBIAN_FRONTEND="noninteractive" apt $APT_OPTIONS install -y --no-install-recommends \
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
    python3-dev \
    libpq-dev \
    python3 \
    python3-pip \
    build-essential \
    git  \ 
    libyaml-dev


RUN install -m 0755 -d /etc/apt/keyrings
RUN curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg

RUN echo \
  "deb [arch=$(dpkg --print-architecture) \
  signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null

RUN apt update && \
apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
# RUN pip install webssh
COPY webssh /root/webssh
RUN pip install --no-cache-dir -e /root/webssh  --break-system-packages

RUN docker --version

COPY launch.sh /root
RUN chmod a+x /root/launch.sh

RUN echo "root:odoo" | chpasswd root

COPY requirements.txt .
RUN apt $APT_OPTIONS install -y python3-venv
RUN python3 -mvenv /usr/local/bin/venv
RUN /usr/local/bin/venv/bin/python3 -mpip install wheel --upgrade
RUN /usr/local/bin/venv/bin/python3 -mpip install -r requirements.txt


RUN sed -i 's/\#PermitRootLogin\ prohibit-password/PermitRootLogin yes/g' /etc/ssh/sshd_config 
RUN cat /etc/ssh/sshd_config |grep Permit
EXPOSE 8080

RUN touch /tmp/iam_webssh

RUN find /usr/local/lib -name webssh
COPY ["font/Meslo LG M Regular for Powerline.ttf", "/usr/local/lib/python3.8/dist-packages/webssh/static/css/fonts"]
#COPY ["font/Lucida Regular.ttf", "/usr/local/lib/python3.8/dist-packages/webssh/static/css/fonts"]

COPY programs/* /root/programs/
RUN mkdir -p /root/.ssh
COPY sshkey/* /root/.ssh/
RUN chmod 500 /root/.ssh && \
chmod 400 /root/.ssh/* && \
echo 'Adding paths to .bash_profile' && \
echo 'readonly PATH=$HOME/programs' >> /root/.bash_profile && \ 
echo 'export PATH' >> /root/.bash_profile && \
chmod a+x /root/programs/*  && \
chsh -s /usr/bin/rbash && \
ln -s /usr/bin/ssh /root/programs/ssh

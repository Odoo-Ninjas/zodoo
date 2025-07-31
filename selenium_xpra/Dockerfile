FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Install dependencies
RUN #___SNIPPET_APT_INSTALL___ \
	wget curl gnupg2 unzip \
    python3 python3-gi \
    xpra \
    fluxbox \
    dbus-x11 \
    libnss3 libxss1 libappindicator3-1 libasound2 \
    libx11-xcb1 libxcomposite1 libxdamage1 libxrandr2 \
    libgtk-3-0 libgbm1 x11-utils \
    fonts-liberation xdg-utils \
	gosu \
	python3-pip 

# Get Chrome version and install matching ChromeDriver

# Install dependencies
RUN apt-get update && apt-get install -y chromium chromium-driver

#___SNIPPET_XPRA_INSTALL___

# Optional: create a user
RUN useradd -m -s /bin/bash user1
USER user1
WORKDIR /home/user1

EXPOSE 5900

COPY start.sh /start.sh

# Entry script
CMD xpra start :100 \
    --bind-tcp=0.0.0.0:5900 \
    --html=on \
    --start-child="/bin/bash /start.sh" \
    --exit-with-children \
    --no-daemon
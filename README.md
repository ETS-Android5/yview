# ICONS
Internet Connection Server for the yView network. This git repo provides the ICON server functionality.

This server exposes a single SSH port (by default 2222). This allows any device offering a service over a TCP socket (E.G web/ssh/vnc server etc) to be securley connected to without passing through a cloud service provider.

Before generating the docker image the ssh/authorized_keys may be changed to include public ssh keys. Public ssh keys can be added to this file for all ICONS gateway or yView Linux/Windows or Android connections.

## Prerequisites
Before this docker image can be used the following must be installed.

 - Docker must be installed in the linux host
 	[Installing Docker on Ubuntu 18.04](https://www.hostinger.com/tutorials/how-to-install-and-use-docker-on-ubuntu/)
 - docker-compose must be also be installed
    `sudo apt-get install docker-compose`
    
## Docker image configuration
The docker-compose.yml file contains some environmental variables that may be changed. These are

### USER
This is set to `changeusername` by default and should be changed before use to a username of your choice.

### USER_PASSWORD
This is the password for the above user. By default this is not set.

### SUDO
This defines whether `sudo` is enabled. The default for this value is true but it maybe set to false if you wish to prohibit sudo access.

### SUDO_REQUIRE_PASSWORD
If SUDO=true then this options is used. If you wish to allow sudo access but require that the user must enter the user password then this option should be set to true. In this case a user password must be set. The default for this value is false.

### ALLOW_SSH_PASSWORD
If this is set to true then a password maybe entered over the ssh connection to login to the ssh server. The default for this option is false. By default the only way to login to the ssh server is to include a public ssh key in the ssh/authorized_keys file.

## Building the docker container
 `docker-compose build`
 
## Starting the docker container
 `docker-compose up`

## Stopping the docker container
 
 `docker-compose stop`


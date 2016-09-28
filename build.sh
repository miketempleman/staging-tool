#use pyinstaller to build a single file executable of the
#staging tool.

# THIS IS ONLY FOR OSX
# To build a single file executable for Linux run this script on the python files
# on the linux target machine. I have no idea how to do this on Windoze

pyinstaller --name staging --onefile main.py

pyinstaller staging.spec
#!/usr/bin/python3

# Check required modules
import importlib

modules=(
    "yaml",
    "socket",
    "argparse",
    "requests",
    "dialog",
    "crontab",
)

missing = []
for module in modules:
    try:
        importlib.import_module(module)
    except ImportError:
        missing.append(module)

if missing:
    print("The following Python3 modules needed:")
    print(" ".join(missing))
    exit(1)

import os
import json
import yaml
import socket
import argparse
import requests
from dialog import Dialog

try:
    from crontab import CronTab
except ImportError:
    CronTab = None

try:
    import apt
except ImportError:
    apt = None

try:
    import dnf
except ImportError:
    dnf = None

class meerkat:

    config={}
    config["general"]={}
    config["general"]["selected_notifications"]=[]
    config["general"]["watched_packages"]=[]
    config["general"]["watcher_file_path"]="/var/lib/package_versions.yml"

    config["notifications"]={}
    config["notifications"]["discord_webhook"]={}
    config["notifications"]["discord_webhook"]["url"]=""



    def __init__(self):
        self.d=Dialog(dialog="dialog", autowidgetsize=True)
        if os.path.isfile("/etc/meerkat/meerkat.yml"):
            self.get_config()
        else:
            self.d.msgbox("\
                We didn\'t find config file!\n\
                \n\
                Please initialize the config file with answering questions!\n\
                \n\
                ", height=9, width=70)
            self.set_config()
            self.get_config()

        self.stored_packages=self.get_package_versions()
        self.actual_packages=self.get_actual_package_versions()


    # Load config file
    def get_config(self):
        with open("/etc/meerkat/meerkat.yml", "r") as file:
            self.config = yaml.safe_load(file)



    # Create or modify config file
    def set_config(self):
        cache = apt.Cache()

        # Get installed packages (name, version)
        packages=[]

        for pkg in cache:
            if pkg.is_installed:
                if pkg.name in self.config["general"]["watched_packages"]:
                    watched="on"
                else:
                    watched="off"
                packages.append((pkg.name, pkg.versions[0].version, watched))

        while True:
            # Show the general form
            code, form_data = self.d.mixedform(
                "Enter general information:",
                [
                    ("Package version file location:", 1, 1, self.config["general"]["watcher_file_path"], 1, 35, 60, 100, 0),  # Single text input field
                ],
            height=10, width=100, form_height=0)

            # Validate that the input is not empty

            if code == self.d.CANCEL:
                os.system("clear")
                exit(0)
            elif code == self.d.OK and len(form_data)>0:
                user_input = form_data[0].strip()
                break  # Exit loop if input is valid

            # Show an error message if input is empty
            self.d.msgbox("File path cannot be empty! Please enter a value.")
        self.config["general"]["watcher_file_path"]="".join(user_input)

        while True:
            # Show the package checklist
            code, selected_packages = self.d.checklist("Select package that would monitor:", choices=packages)

            # Ensure at least one selection
            if code == self.d.CANCEL:
                os.system("clear")
                exit(0)
            elif code == self.d.OK and selected_packages:
                break  # Exit the loop if at least one item is selected

            # Show an error message and re-show the checklist
            self.d.msgbox("You must select at least one package!", height=5, width=70)
        self.config["general"]["watched_packages"]=selected_packages


        notifications=[
            ("Discord Webhook", "", "off")
        ]

        while True:
            # Show the notification checklist
            code, selected_notifications = self.d.checklist("Select notification types:", choices=notifications)

            # Ensure at least one selection
            if code == self.d.CANCEL:
                os.system("clear")
                exit(0)
            if code == self.d.OK and selected_notifications:
                break  # Exit the loop if at least one item is selected

            # Show an error message and re-show the checklist
            self.d.msgbox("You must select at least one notification!", height=5, width=70)
        self.config["general"]["selected_notifications"]=selected_notifications


        if "Discord Webhook" in selected_notifications:
            while True:
                # Show the discord form
                code, form_data = self.d.mixedform(
                    "Enter Discord information:",
                    [
                        ("Webhook URL:", 1, 1, self.config["notifications"]["discord_webhook"]["url"], 1, 35, 60, 150, 0),  # Single text input field
                    ],
                height=10, width=100, form_height=0)

                # Validate that the input is not empty
                if code == self.d.CANCEL:
                    os.system("clear")
                    exit(0)
                if code == self.d.OK and len(form_data)>0:
                    user_input = form_data[0].strip()
                    break  # Exit loop if input is valid

                # Show an error message if input is empty
                self.d.msgbox("Url cannot be empty! Please enter a value.")
            self.config["notifications"]["discord_webhook"]["url"]="".join(user_input)

            if CronTab:
                command = '/usr/bin/python3 '+os.path.realpath(__file__)
                cron = CronTab(user=True)
                job_exists = any(job.command == command for job in cron)

                if not job_exists:

                    confirm=self.d.yesno("Would you like to create crontab entry?", height=None, width=None)

                    if confirm=="ok":
                        job = cron.new(command)
                        job.setall("@reboot")
                        cron.write()
            else:
                print("Crontab module is required!")

        if not os.path.exists("/etc/meerkat"):
            os.makedirs("/etc/meerkat")

        with open("/etc/meerkat/meerkat.yml", "w") as file:
            yaml.dump(self.config, file, default_flow_style=False)

        self.actual_packages=self.get_actual_package_versions()
        self.set_package_versions()

        os.system("clear")
        exit(0)



    # Get currently installed packages via OS package manager module
    def get_actual_package_versions(self):

        packages = {}

        if apt:
            cache = apt.Cache()
            for pkg in cache:
                if pkg.is_installed and pkg.name in self.config["general"]["watched_packages"]:
                    packages[pkg.name] = pkg.installed.version
        elif dnf:
            base = dnf.Base()
            base.fill_sack()
            installed = base.sack.query().installed()
            for pkg in installed:
                if pkg.name in self.config["general"]["watched_packages"]:
                    packages[pkg.name] = pkg.evr
        else:
            raise RuntimeError("Neither apt nor dnf module found.")
            exit(1)

        return packages



    # check diffs between stored and installed packages
    def check_package_versions(self):

        changes=[]

        for name,version in self.stored_packages.items():
            if version!=self.actual_packages[name]:
                changes.append(name+": "+version+" -> "+self.actual_packages[name])

        return changes



    # send notify to selected channels
    def notify(self, dryrun=False):

        changes=self.check_package_versions()
        title = "Changes on "+socket.getfqdn()+" host: \n"

        if dryrun:
            print(title+"\n".join(changes))
            return 0

        if changes:
            for noti in self.config["general"]["selected_notifications"]:

                # Discord notification
                if "Discord Webhook" in self.config["general"]["selected_notifications"]:
                        data = {"content": "**"+title+"**"+"\n".join(changes)}
                        headers = {'Content-Type': 'application/json'}
                        requests.post(self.config["notifications"]["discord_webhook"]["url"], data=json.dumps(data), headers=headers)

            self.set_package_versions()
        else:
            print("No changes in watched packages.")
            return 0



    # Save currently installed package versions to file
    def set_package_versions(self):
        with open(self.config["general"]["watcher_file_path"], "w") as file:
            yaml.dump(self.actual_packages, file, default_flow_style=False)



    # Load stored package versions
    def get_package_versions(self):
        if os.path.isfile(self.config["general"]["watcher_file_path"]):
            with open(self.config["general"]["watcher_file_path"], "r") as file:
                packages = yaml.safe_load(file)
            return packages
        else:
            print("No version file found! Please init it first!")
            exit(1)


### MAIN ###

app=meerkat()

parser = argparse.ArgumentParser(description="Meerkat - Package version notifier")

# Add arguments
parser.add_argument("-c", "--config", action="store_true", help="Init or modify app configuration")
parser.add_argument("-n", "--notify", action="store_true", help="Run the notification")
parser.add_argument("-d", "--dry-run", action="store_true", help="Just test, does not send notifications")

# Parse the arguments
args = parser.parse_args()

# Access the values
if args.config:
    app.set_config()
elif args.notify:
    app.notify()
elif args.dry_run:
    app.notify(True)
else:
    parser.print_help()

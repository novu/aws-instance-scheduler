######################################################################################################################
#  Copyright 2016 Amazon.com, Inc. or its affiliates. All Rights Reserved.                                           #
#                                                                                                                    #
#  Licensed under the Amazon Software License (the "License"). You may not use this file except in compliance        #
#  with the License. A copy of the License is located at                                                             #
#                                                                                                                    #
#      http://aws.amazon.com/asl/                                                                                    #
#                                                                                                                    #
#  or in the "license" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES #
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions    #
#  and limitations under the License.                                                                                #
######################################################################################################################

# bucket name to deploy to
ifndef bucket
bucket=instance-scheduler-deploy
endif

# prefix of deployed artifacts in bucket
ifndef prefix
prefix = instance-scheduler/latest/
endif

s3bucket=s3://$(bucket)/

s3http='https:\/\/s3-eu-west-1.amazonaws.com\/$(bucket)'

pydirs= configuration configuration/setbuilders requesthandlers schedulers util boto_retry
py=$(foreach dir, $(pydirs), $(wildcard $(dir)/*.py))

cli_dirs = ./cli ./cli/scheduler_cli
pycli=$(foreach dir, $(cli_dirs), $(wildcard $(dir)/*.py))


# ops automator templates
templates=$(wildcard ../cloudformation/*.template)

version=`cat version.txt`

deployment=../../deployment
zip = $(deployment)/instance-scheduler-$(version).zip
zip_cli = $(deployment)/scheduler-cli-$(version).zip
pwd=`pwd`

build: lambda cfn cli

######################################################################################################################
# lambda code                                                                                                        #
######################################################################################################################

lambda:$(py) main.py version.txt

	# delete old zip files
	find $(deployment) -maxdepth 1 -type f -name 'instance-scheduler-*.zip' -delete

	mkdir -p $(deployment)
	zip  $(zip) version.txt
	mv main.py main.py.org
	sed s/%version%/$(version)/g main.py.org > main.py
	zip  $(zip) main.py
	rm main.py
	mv main.py.org main.py
	zip -r $(zip)  $(py)  version.txt
	zip -r -q $(zip) pytz


######################################################################################################################
# cli                                                                                                                #
######################################################################################################################

cli:$(pycli) version.txt

	# delete old deployments
	find $(deployment) -maxdepth 1 -type f -name 'scheduler-cli-*.zip' -delete

	mkdir -p $(deployment)

	mv cli/scheduler_cli/scheduler_cli.py cli/scheduler_cli/scheduler_cli.org
	sed s/#version#/$(version)/g cli/scheduler_cli/scheduler_cli.org > cli/scheduler_cli/scheduler_cli.py
	cp version.txt cli/version.txt
	cd ./cli && zip -r ../$(zip_cli) scheduler_cli/*.py
	rm cli/scheduler_cli/scheduler_cli.py
	mv cli/scheduler_cli/scheduler_cli.org cli/scheduler_cli/scheduler_cli.py
	mv cli/setup.py cli/setup.org
	sed s/#version#/$(version)/g cli/setup.org > cli/setup.py
	cd ./cli && zip ../$(zip_cli) setup.py instance-scheduler-cli-runner.py
	rm cli/version.txt
	rm cli/setup.py
	mv cli/setup.org cli/setup.py
	cp $(zip_cli) $(deployment)/scheduler-cli-latest.zip




######################################################################################################################
# cloudformation templates                                                                                           #
######################################################################################################################

cfn:version.txt $(templates)
	mkdir -p $(deployment)

	# delete old templates
	find $(deployment) -maxdepth 1 -type f -name 'instance-scheduler-*.template' -delete

	# build main template
	python ./build-instance-scheduler-template.py ../cloudformation/instance-scheduler.template  $(version) $(bucket) $(prefix) > $(deployment)/instance-scheduler-$(version).template
	cp $(deployment)/instance-scheduler-$(version).template  $(deployment)/instance-scheduler-latest.template

	# template for setting cross account role
	sed s/%version%/$(version)/g ../cloudformation/instance-scheduler-remote.template > $(deployment)/instance-scheduler-remote-$(version).template
	cp  $(deployment)/instance-scheduler-remote-$(version).template $(deployment)/instance-scheduler-remote-latest.template

######################################################################################################################
# Deploy to S3                                                                                                       #
######################################################################################################################

deploy: lambda cfn cli
	aws s3 cp $(deployment)/instance-scheduler-latest.template $(s3bucket)$(prefix)  --acl public-read
	aws s3 cp $(deployment)/instance-scheduler-latest.template $(s3bucket)  --acl public-read

	aws s3 cp $(deployment)/instance-scheduler-remote-latest.template $(s3bucket)$(prefix)  --acl public-read
	aws s3 cp $(deployment)/instance-scheduler-remote-latest.template $(s3bucket)  --acl public-read

	aws s3 cp $(zip) $(s3bucket)$/$(prefix)  --acl public-read
	aws s3 cp $(zip_cli) $(s3bucket)$(prefix) --acl public-read
	aws s3 cp $(deployment)/scheduler-cli-latest.zip $(s3bucket) --acl public-read

	python update-build-number.py version.txt


	#next few lines during developement only
	sleep 15
	aws cloudformation update-stack --stack-name InstanceScheduler --template-url https://s3-eu-west-1.amazonaws.com/instance-scheduler-deploy/instance-scheduler-latest.template --capabilities CAPABILITY_IAM --parameters "`aws cloudformation describe-stacks --stack-name InstanceScheduler --query Stacks[0].Parameters[]`"








	

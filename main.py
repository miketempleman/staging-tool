import boto
import boto.route53
import boto.route53.record
import boto.ec2.elb
import os
import argparse
import sys
import time
import base64


def uploadCB(done, total):
    s = '%d bytes transferred out of %d, uploaded %d%%     ' % (done, total, (done * 100) / total)
    sys.stdout.write('\r')
    sys.stdout.flush()
    sys.stdout.write(s)


def startDB():
    ec2 = boto.connect_ec2()
    instances = ec2.get_only_instances(filters={'tag:Name': 'DB Staging'})
    for instance in instances:
        status = instance.update()
        if status in ('running', 'pending'):
            print("Already found DB")
            return

    userdataPath = os.path.expanduser('~/git/scripts/dbstaging-init.sh')
    data = ""
    with open(userdataPath, "r") as myfile:
        data = myfile.read()
    elb = boto.ec2.elb.coennect_to_region('us-east-1')
    reservation = ec2.run_instances(image_id='ami-2c762344', placement='us-east-1a', instance_type="m3.medium",
                                    dry_run=False, key_name='ec2key', user_data=data, security_groups=["MongoDB"],
                                    min_count=1, max_count=1,
                                    instance_profile_arn="arn:aws:iam::284541662771:instance-profile/DBStaging")
    for instance in reservation.instances:
        status = instance.update()
        while status == 'pending':
            print("Waiting on DB Staging to start to tag. Sleeping for 10 seconds before polling again")
            time.sleep(10)
            status = instance.update()
        if status == 'running':
            instance.add_tag("Name", "DB Staging")
            print ("started " + instance.id + " successfully")
        else:
            print('Instance status: ' + status)
            instance.add_tag("Name", "Dead--Staging App Server")

    ip_addr = reservation.instances[0].private_ip_address
    zone = boto.route53.connect_to_region('us-east-1').get_zone('db.meshfire.com')
    dbstaging = zone.get_a('staging.db.meshfire.com')
    zone.update_record(dbstaging, ip_addr)
    print ("started Db Staging successfully and updated DNS. Waiting 60 seconds for DNS servers to refresh (TTL=60)")
    for i in range(0, 30):
        sys.stdout.write('.')
        time.sleep(2)


def upload():
    print("Upload staging app server war to the s3 plover-staging bucket")
    s3 = boto.connect_s3()
    bucket = s3.get_bucket('plover-staging')
    key = bucket.get_key('plover.war')
    targetpath = os.path.expanduser('~/git/plover/plover/target/plover-1.00.war')
    print("Uploading " + targetpath + " to plover-staging")
    key.set_contents_from_filename(targetpath, cb=uploadCB, num_cb=100)
    print("\nCompleted uploading " + targetpath + " to plover-staging")


def startup(n):
    print('\n\nStarting %d staging server(s)' % (n))
    ec2 = boto.connect_ec2()
    userdataPath = os.path.expanduser('~/git/scripts/startup-iam-staging.sh')
    data = ""
    elb = boto.ec2.elb.connect_to_region('us-east-1')
    stagingELB = boto.ec2.elb.connect_to_region('us-east-1').get_all_load_balancers(load_balancer_names=['staging'])[0]
    instanceIDs = []
    with open(userdataPath, "r") as myfile:
        data = myfile.read()
    reservation = ec2.run_instances(image_id='ami-a36b81ce', instance_type="c3.xlarge", dry_run=False, key_name='ec2key',
                                    user_data=data, security_groups=["plover-default"], min_count=n, max_count=n,
                                    instance_profile_arn="arn:aws:iam::284541662771:instance-profile/Meshfire")
    for instance in reservation.instances:
        status = instance.update()
        while status == 'pending':
            print(
                "Waiting on instance to start to tag and attach to load balancer. Sleeping for 10 seconds before polling again")
            time.sleep(10)
            status = instance.update()
        if status == 'running':
            instance.add_tag("Name", "Staging App Server")
            print ("started " + instance.id + " successfully")
            instanceIDs.insert(0, instance.id)
        else:
            print('Instance status: ' + status)
            instance.add_tag("Name", "Dead--Staging App Server")
    stagingELB.register_instances(instanceIDs)
    print ('\n %d instances started or attempted to start' % (n))


def stopDB():
    print("Stopping DB Staging")
    instances = boto.connect_ec2().get_only_instances(filters={'tag:Name': 'DB Staging'})
    for instance in instances:
        status = instance.update()
        if status in ('running', 'pending'):
            instance.terminate()

    return instanceCount


def stop():
    print("Stopping staging app servers only")
    instanceCount = 0
    elb = boto.ec2.elb.connect_to_region('us-east-1')
    stagingELB = boto.ec2.elb.connect_to_region('us-east-1').get_all_load_balancers(load_balancer_names=['staging'])[0]
    instance_ids = [instance.id for instance in stagingELB.instances]
    if (len(instance_ids) > 0):
        stagingELB.deregister_instances(instance_ids)
        reservations = boto.ec2.connect_to_region('us-east-1').get_all_reservations(instance_ids=instance_ids)
        for instance in reservations[0].instances:
            if 'Name' in instance.tags and instance.tags['Name'] == "Staging App Server":
                instance.terminate()
                instanceCount += 1
    print("\nAll Staging instances stopped.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Meshfire staging server control tool")
    parser.add_argument('-s', '--stop', dest="stop", action='store_true',
                        help='Stop all servers connected to staging environment')
    parser.add_argument('-u', '--upload', dest="upload", action='store_true',
                        help="Only upload staging war to plover-staging")
    parser.add_argument('-st', '--start', dest="start", type=int, metavar="N",
                        help="Start N servers and connect to staging load balancer. Does not stop existing servers")
    parser.add_argument('-r', '--restart', dest="restart", type=int, metavar="N",
                        help="Stop all servers, upload new staging war then start N servers and connect to staging load balancer")
    parser.add_argument('-db', '--startdb', dest="startDB", action='store_true', help="Start staging database server")
    parser.add_argument('-sa', '--stopAll', dest="stopAll", action='store_true',
                        help="Stop all app servers and staging database server")


    args = parser.parse_args()

    if args.stop:
        stop()

    if args.upload:
        upload()

    if args.start:
        startDB()
        startup(args.start)

    if args.restart:
        upload()
        stop()
        startDB()
        startup(args.restart)

    if args.startDB:
        startDB()

    if args.stopAll:
        stop()
        stopDB()

    print("finished")

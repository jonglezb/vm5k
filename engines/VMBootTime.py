#!/usr/bin/env python
from vm5k.engine import *
#from itertools import product, repeat
import sys
import time
import datetime
import string


class VMBootMeasurement(vm5k_engine_para):
    def __init__(self):
        super(VMBootMeasurement, self).__init__()
        self.n_nodes = 1
        self.options_parser.add_option("--vm",
            dest="n_vm", type="int", default=1,
            help="maximum number of VMs")
        self.options_parser.add_option("--cpu",
            dest="n_cpu", type="int", default=1,
            help="maximum number of CPUs")
        self.options_parser.add_option("--mem",
            dest="n_mem", type="int", default=1,
            help="maximum number of memory")

    def define_parameters(self):
        """Define the parameters you want to explore"""
        #self.cpu_topology = get_cpu_topology(cluster, xpdir=self.result_dir)
        parameters = {
            'n_mem': range(1, self.options.n_mem + 1),
            'n_cpu': range(1, self.options.n_cpu + 1),
            'n_vm': range(1, self.options.n_vm + 1),
            'vm_policy': ['one_vm_per_core', 'vm_one_core'],
            'image_policy': ['one', 'one_per_vm'],
            'vm_boot_policy': ['all_at_once','one_then_others']}

        logger.debug(parameters)

        return parameters

    def comb_nvm(self, comb):
        """Calculate the number of virtual machines in the combination,
required to attribute a number of IP/MAC for a parameter combination """
        n_vm = comb['n_vm']
        return n_vm

    def workflow(self, comb, hosts, ip_mac):
        """Perform a boot measurements on the VM """
        host = hosts[0]

        logger.debug('hosts %s', host)
        logger.debug('ip_mac %s', ip_mac)

        thread_name = style.Thread(host.split('.')[0]) + ': '
        comb_ok = False
        try:
            logger.info(thread_name)
            logger.info(style.step('Performing combination ' + slugify(comb)))

            logger.detail(thread_name + 'Destroying all vms on hosts')
            destroy_vms(hosts)

            cpusets = []

            if comb['vm_policy'] == 'one_vm_per_core':
                for i in range(comb['n_vm']):
                    cpusets.append(','.join(str(i)
                            for j in range(comb['n_cpu'])))
            else:
                for i in range(comb['n_vm']):
                    cpusets.append(str(0))

            backing_file = '/home/lpouilloux/synced/images/benchs_vms.qcow2'
            real_file = True if comb['image_policy'] == 'one_per_vm' else False

            # Define the virtual machines for the combination
            vms = define_vms(['vm-' + str(i) for i in range(comb['n_vm'])],
                              ip_mac=ip_mac,
                              host=hosts[0],
                              n_cpu=comb['n_cpu'],
                              cpusets=cpusets,
                              mem=comb['n_mem'] * 1024,
                              backing_file=backing_file,
                              real_file=real_file)
            for vm in vms:
                vm['host'] = hosts[0]

            # Create disks, install vms and boot by core
            logger.info(thread_name + ': Creating disks')
                
            create = create_disks(vms).run()
            if not create.ok:
                logger.error(thread_name + 'Unable to create the VMS disks %s',
                             slugify(comb))
                exit()

            logger.info(thread_name + 'Installing VMS')
            install = install_vms(vms).run()
            if not install.ok:
                logger.error(host + ': Unable to install the VMS  %s',
                             slugify(comb))
                exit()
                
            logger.info(style.Thread(host)+': Starting VMS '+', '.join( [vm['id'] for vm in sorted(vms)]))
            
            Remote('echo 3 > /proc/sys/vm/drop_caches', [hosts[0]]).run()
            
            mpstat = Remote('mpstat 5 -P ALL > /tmp/mpstats', [hosts[0]]).start()
            
            now = time.time()
            
            if comb['vm_boot_policy'] == 'all_at_once':
                start_vms(vms).run()
                booted = wait_vms_have_started(vms)
                if not booted:
                    logger.error(host + ': Unable to boot all the VMS for %s',
                                 slugify(comb))
                    exit()
                    
                get_uptime = TaktukRemote('cat /proc/uptime', [vm['ip']
                                    for vm in vms]).run()
                boot_time = {}
                for p in get_uptime.processes:
                    boot_time[p.host.address] = now - float(p.stdout.strip().split(' ')[0])
                
                get_ssh_up = TaktukRemote('grep listening /var/log/auth.log' + \
                            ' |grep 0.0.0.0|awk \'{print $1" "$2" "$3}\' | tail -n 1',
                            [vm['ip'] for vm in vms]).run()
                
                boot_duration = []
                for p in get_ssh_up.processes:
                    ssh_up = time.mktime(datetime.datetime.strptime('2014 ' + \
                            p.stdout.strip(), "%Y %b %d %H:%M:%S").timetuple())
                    boot_duration.append(str(ssh_up - boot_time[p.host.address]))
    
                uptime = string.join(boot_duration, ",")
            else:
                first_vm = [] 
                first_vm.append(vms[0])
                
                others_vms = vms[1:]
                
                start_vms(first_vm).run()
                booted = wait_vms_have_started(first_vm)
                if not booted:
                    logger.error(host + ': Unable to boot all the VMS for %s',
                                 slugify(comb))
                    exit()
                    
                get_uptime = TaktukRemote('cat /proc/uptime', [vm['ip']
                                    for vm in first_vm]).run()
                boot_time = {}
                for p in get_uptime.processes:
                    boot_time[p.host.address] = now - float(p.stdout.strip().split(' ')[0])
                
                get_ssh_up = TaktukRemote('grep listening /var/log/auth.log' + \
                            ' |grep 0.0.0.0|awk \'{print $1" "$2" "$3}\' | tail -n 1',
                            [vm['ip'] for vm in first_vm]).run()
                
                boot_duration = []
                for p in get_ssh_up.processes:
                    ssh_up = time.mktime(datetime.datetime.strptime('2014 ' + \
                            p.stdout.strip(), "%Y %b %d %H:%M:%S").timetuple())
                    boot_duration.append(str(ssh_up - boot_time[p.host.address]))
    
    
                if len(others_vms) != 0:
                    start_vms(others_vms).run()
                    booted = wait_vms_have_started(others_vms)
                    if not booted:
                        logger.error(host + ': Unable to boot all the VMS for %s',
                                     slugify(comb))
                        exit()
                        
                    get_uptime = TaktukRemote('cat /proc/uptime', [vm['ip']
                                        for vm in others_vms]).run()
                    boot_time = {}
                    for p in get_uptime.processes:
                        boot_time[p.host.address] = now - float(p.stdout.strip().split(' ')[0])
                    
                    get_ssh_up = TaktukRemote('grep listening /var/log/auth.log' + \
                                ' |grep 0.0.0.0|awk \'{print $1" "$2" "$3}\' | tail -n 1',
                                [vm['ip'] for vm in other_vms]).run()
                    
                    for p in get_ssh_up.processes:
                        ssh_up = time.mktime(datetime.datetime.strptime('2014 ' + \
                                p.stdout.strip(), "%Y %b %d %H:%M:%S").timetuple())
                        boot_duration.append(str(ssh_up - boot_time[p.host.address]))
        
    
                uptime = string.join(boot_duration, ",")
            
            mpstat.kill()
            
            # Get load on host
            get_load = TaktukRemote('cat /proc/loadavg',
                            [hosts[0]]).run()
            
            load_host = []
            
            for p in get_load.processes:
                load_host.append(p.stdout.strip())
            
            load_data = string.join(load_host, ",")
                         # Gathering results
            comb_dir = self.result_dir + '/' + slugify(comb) + '/'
            try:
                mkdir(comb_dir)
            except:
                logger.warning(thread_name +
                    '%s already exists, removing existing files', comb_dir)
                for f in listdir(comb_dir):
                    remove(comb_dir + f)

            logger.info(thread_name + 'Writing boot time in result files')

            text_file = open(comb_dir+"boot_time.txt", "w")
            text_file.write(uptime+'\n')
            text_file.write(load_data+'\n')
            text_file.close()
            
            get_mpstat_output = Get([hosts[0]], ['/tmp/mpstats'],
                                     local_location=comb_dir).run()
            for p in get_mpstat_output.processes:
                if not p.ok:
                    logger.error(host +
                        ': Unable to retrieve the files for combination %s',
                        slugify(comb))
                    exit()

            comb_ok = True

        finally:
            if comb_ok:
                self.sweeper.done(comb)
                logger.info(thread_name + ': ' + slugify(comb) + \
                             ' has been done')
            else:
                self.sweeper.cancel(comb)
                logger.warning(thread_name + ': ' + slugify(comb) + \
                            ' has been canceled')
            logger.info(style.step('%s Remaining'),
                        len(self.sweeper.get_remaining()))

    def setup_hosts(self):
        """ """
        logger.info('Initialize vm5k_deployment')
        setup = vm5k_deployment(resources=self.resources,
            env_name=self.options.env_name, env_file=self.options.env_file)
        setup.fact = ActionFactory(remote_tool=TAKTUK,
                                fileput_tool=CHAINPUT,
                                fileget_tool=SCP)
        logger.info('Deploy hosts')
        setup.hosts_deployment()
        logger.info('Install packages')
        setup.packages_management(other_packages='sysstat')
        logger.info('Configure libvirt')
        setup.configure_libvirt()
        logger.info('Create backing file')
        setup._create_backing_file(disks=['/home/lpouilloux/synced/images/benchs_vms.qcow2'])


if __name__ == "__main__":
    engine = VMBootMeasurement()
    engine.start()
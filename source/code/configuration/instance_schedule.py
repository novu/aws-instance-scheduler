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


from datetime import datetime, timedelta

import configuration
import pytz
from util.named_tuple_builder import as_namedtuple

ERR_STOP_MUST_BE_LATER_OR_EQUAL_TO_START = "stop_date must be equal or later than start_date"

DEBUG_ACTIVE_PERIOD_IN_SCHEDULE = "Active period{} in schedule \"{}\": {}"
DEBUG_NO_RUNNING_PERIODS = "No running periods at this time found in schedule \"{}\" for this time, desired state is {}"
DEBUG_OVERRIDE_STATUS = "Schedule override_status value is {}, desired state is {}"
DEBUG_SCHEDULE = "Schedule is {}"
DEBUG_SET_DESIRED_INSTANCE_TYPE = "Current type of instance is {}, desired type is {}, desired state is set to {} to " \
                                  "restart instance with the desired type"
DEBUG_STATE_ANY = "\"Any\" state period found for current time in schedule \"{}\", desired state is {}"
DEBUG_USED_PERIOD = "Using period \"{}\" to set the desired state and instance size"
DEBUG_USED_TIME_FOR_SCHEDULE = "Time used to determine desired for instance is {}"


class InstanceSchedule:
    """
    Implements an instance schedule
    """
    STATE_UNKNOWN = "unknown"
    STATE_ANY = "any"
    STATE_STOPPED = "stopped"
    STATE_RUNNING = "running"
    STATE_RETAIN_RUNNING = "retain-running"
    STATE_STANDBY = "standby"

    def __init__(self, name, periods=None, timezone=None, override_status=None, description=None, use_metrics=None,
                 stop_new_instances=None, schedule_dt=None, use_maintenance_window=False, enforced=False, retain_running=False):
        """
        Initializes a schedule instance
        :param name: Name of a schedule
        :param periods: Periods in which instances are running
        :param timezone: Timezone of the schedule (default = UTC)
        :param override_status: Set to have instances always started or stopped
        :param description: Description of the schedule
        :param use_metrics: Set to true to collect metrics for the schedule
        :param stop_new_instances: Set to True to stop instances that are added to the schema if they are not in a running period
        :param schedule_dt: datetime to use for scheduling
        :param use_maintenance_window: Set to True to use the maintenance window as an additional schedule in
        which instances are running
        :param: enforce start/stop state of the schema on instances
        """
        self.name = name
        self.periods = periods
        self.timezone = timezone
        self.override_status = override_status
        self.description = description
        self.stop_new_instances = stop_new_instances
        self.use_maintenance_window = use_maintenance_window
        self.use_metrics = use_metrics
        self.enforced = enforced
        self.retain_running = retain_running
        self.schedule_dt = schedule_dt if schedule_dt is not None else datetime.now(pytz.timezone(self.timezone))
        self._logger = None

    def _log_info(self, msg, *args):
        if self._logger is not None:
            self._logger.info(msg, *args)

    def _log_debug(self, msg, *args):
        if self._logger is not None:
            self._logger.debug(msg, *args)

    def __str__(self):
        s = "Schedule \"{}\": ".format(self.name)
        attributes = []
        if self.description:
            attributes.append(" ({})".format(self.description))
        if self.override_status is not None:
            attributes.append("always {} through override_status".format("running" if self.override_status else "stopped"))
        if self.timezone:
            attributes.append("timezone is {}".format(str(self.timezone)))
        if self.stop_new_instances is not None:
            attributes.append("new instanced are {}stopped".format("" if self.stop_new_instances else "not "))
        if self.use_maintenance_window is not None:
            attributes.append("maintenance windows are {}used to start instances".format("" if self.stop_new_instances else "not "))
        if self.enforced is not None:
            attributes.append("schedule state is {}enforced to start or stop instances".format("" if self.enforced else "not "))
        if self.retain_running is not None:
            attributes.append(
                "instances are {}stopped if at the and of a period if they were already running at the start of the period".format(
                    "not" if self.retain_running else ""))

        if self.periods and len(self.periods) > 0:
            pl = []
            for p in self.periods:
                ps = "{}".format(str(p["period"].name))
                if "instancetype" in p and p["instancetype"] is not None:
                    ps += ":instancetype {}".format(p["instancetype"])
                pl.append(ps)
            attributes.append("periods: [" + ", ".join(pl) + ']')
        s += "\n".join(attributes)
        return s

    def get_desired_state(self, instance, logger=None, dt=None):
        """
        Test if an instance should be running at a specific moment in this schedule
        :param instance: the instance to test
        :param logger: logger for logging output of scheduling logic
        :param dt: date time to use for scheduling, use Non for using the time specified in the constructor of the schedule
        :return: desired state, instance type and name of the active period of the schedule if the state is running
        """

        # gets the local time using the configured timezone
        def get_check_time(time):
            check_time = time if time else self.schedule_dt
            return check_time.astimezone(pytz.timezone(self.timezone))

        # actions for desired state is running
        def handle_running_state(inst, periods):

            # used to determining most nearest period if more than one period returns a running state in a schedule
            def latest_starttime(p1, p2):
                if p1["period"].begintime is None:
                    return p2
                if p2["period"].begintime is None:
                    return p1
                return p1 if p1["period"].begintime > p2["period"].begintime else p2

            # test if we need to change the type of the instance
            def requires_adjust_instance_size(desired_instance_type, checked_instance):
                return checked_instance.allow_resize and desired_instance_type is not None and checked_instance.is_running and \
                       desired_instance_type != checked_instance.instancetype

            # reduce is removed from python3, replace by minimal implementation for python3 compatibility
            def _reduce(fn, items):
                if items is None or len(items) == 0:
                    return None
                else:
                    result = items[0]
                    i = 1
                    while i < len(list(items)):
                        result = fn(result, items[i])
                        i += 1
                    return result

            # nearest period in schedule with running state
            current_running_period = _reduce(latest_starttime, periods)

            multiple_active_periods = len(list(periods)) > 1

            self._log_debug(DEBUG_ACTIVE_PERIOD_IN_SCHEDULE.format("s" if multiple_active_periods else "", self.name,
                                                                   ",".join('"' + per["period"].name + '"' for per in periods)))
            if multiple_active_periods:
                self._log_debug(DEBUG_USED_PERIOD.format(current_running_period["period"].name))

            desired_state = InstanceSchedule.STATE_RUNNING
            desired_type = current_running_period["instancetype"] if inst.allow_resize else None

            # check if the instance type matches the desired type, if not set the status to stopped if the instance is currently
            # and the instance will be started with the desired type at the next invocation
            if requires_adjust_instance_size(desired_type, inst):
                desired_state = InstanceSchedule.STATE_STOPPED
                self._log_debug(DEBUG_SET_DESIRED_INSTANCE_TYPE, inst.instancetype, desired_type, desired_state)
            return desired_state, desired_type, current_running_period["period"].name

        # actions for desired state is any state
        def handle_any_state():
            desired_state = InstanceSchedule.STATE_ANY
            self._log_debug(DEBUG_STATE_ANY, self.name, desired_state)
            return desired_state, None, None

        # actions for desired state is stopped
        def handle_stopped_state():
            desired_state = InstanceSchedule.STATE_STOPPED
            self._log_debug(DEBUG_NO_RUNNING_PERIODS, self.name, desired_state)
            return desired_state, None, None

        # actions if there is an override value set for the schema
        def handle_override_status():
            desired_state = InstanceSchedule.STATE_RUNNING if self.override_status == configuration.OVERRIDE_STATUS_RUNNING \
                else InstanceSchedule.STATE_STOPPED
            self._log_debug(DEBUG_OVERRIDE_STATUS, self.override_status, desired_state)
            return desired_state, None, "override_status"

        self._logger = logger

        # always on or off
        if self.override_status is not None:
            return handle_override_status()

        # test if time is withing any period of the schedule
        localized_time = get_check_time(dt)

        self._log_debug(DEBUG_USED_TIME_FOR_SCHEDULE, localized_time.strftime("%c"))

        # get the desired state for every period in the schedule
        periods_with_desired_states = [
            {
                "period": p["period"], "instancetype": p.get("instancetype", None),
                "state": p["period"].get_desired_state(self._logger, localized_time)
            }
            for p in self.periods]

        # get periods from the schema that have a running state
        periods_with_running_state = [p for p in periods_with_desired_states if p["state"] == InstanceSchedule.STATE_RUNNING]

        if any(periods_with_running_state):
            return handle_running_state(instance, periods_with_running_state)

        period_with_any_state = filter(lambda period: period["state"] == InstanceSchedule.STATE_ANY, periods_with_desired_states)
        if any(period_with_any_state):
            return handle_any_state()

        return handle_stopped_state()

    def get_usage(self, start_dt, stop_dt=None, instance=None, logger=None):
        """
           Get running periods for a schedule in a period
           :param instance: instance id
           :param start_dt: start date of the period, None is today
           :param stop_dt: end date of the period, None is today
           :param logger: logger for output of scheduling logic
           :return: dictionary containing the periods in the specified in which instances are running as well as the % saving
           in running hours
           """
        result = {}

        def running_seconds(startdt, stopdt):
            return max(int((stopdt - startdt).total_seconds()), 60)

        def running_hours(startdt, stopdt):
            return int(((stopdt - startdt).total_seconds() - 1) / 3600) + 1

        def make_period(started_dt, stopped_dt, inst_type):
            running_period = ({
                "begin": started_dt,
                "end": stopped_dt,
                "billing_hours": running_hours(started_dt, stopped_dt),
                "billing_seconds": running_seconds(started_dt, stopped_dt)
            })
            if inst_type is not None:
                running_period["instancetype"] = inst_type
            return running_period

        self._logger = logger

        stop = stop_dt or start_dt
        if start_dt > stop:
            raise ValueError(ERR_STOP_MUST_BE_LATER_OR_EQUAL_TO_START)

        dt = start_dt if isinstance(start_dt, datetime) else datetime(start_dt.year, start_dt.month, start_dt.day)
        while dt <= stop:

            timeline = {dt.replace(hour=0, minute=0)}
            for p in self.periods:
                begintime = p["period"].begintime
                endtime = p["period"].endtime
                if begintime is None and endtime is None:
                    timeline.add(dt.replace(hour=0, minute=0))
                    timeline.add(dt.replace(hour=23, minute=59))
                else:
                    if begintime:
                        timeline.add(dt.replace(hour=begintime.hour, minute=begintime.minute))
                    if endtime:
                        timeline.add(dt.replace(hour=endtime.hour, minute=endtime.minute))

            running_periods = {}
            started = None
            starting_period = None
            current_state = None
            instance_type = None
            inst = instance or as_namedtuple("Instance", {"instance_str": "instance", "allow_resize": False})
            for tm in sorted(list(timeline)):
                desired_state, instance_type, period = self.get_desired_state(inst, self._logger, tm)

                if current_state != desired_state:
                    if desired_state == InstanceSchedule.STATE_RUNNING:
                        started = tm
                        current_state = InstanceSchedule.STATE_RUNNING
                        starting_period = period
                    elif desired_state == InstanceSchedule.STATE_STOPPED:
                        stopped = tm
                        if current_state == InstanceSchedule.STATE_RUNNING:
                            current_state = InstanceSchedule.STATE_STOPPED
                            running_periods[starting_period] = (make_period(started, stopped, instance_type))

            if current_state == InstanceSchedule.STATE_RUNNING:
                stopped = dt.replace(hour=23, minute=59) + timedelta(minutes=1)
                running_periods[starting_period] = (make_period(started, stopped, instance_type))

            result[str(dt.date())] = {
                "running_periods": running_periods,
                "billing_seconds": sum([running_periods[ps]["billing_seconds"] for ps in running_periods]),
                "billing_hours": sum([running_periods[ph]["billing_hours"] for ph in running_periods])
            }

            dt += timedelta(days=1)

        return {"schedule": self.name, "usage": result}

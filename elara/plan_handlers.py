import numpy as np
from math import floor
import pandas as pd
import os
from datetime import datetime, timedelta

from elara.factory import Tool, WorkStation, ChunkWriter


class PlanHandlerTool(Tool):
    """
    Base Tool class for Plan Handling.
    """
    def __init__(self, config, option=None):
        super().__init__(config, option)

    def build(self, resources: dict) -> None:
        super().build(resources)

    @staticmethod
    def generate_indices_map(list_in):
        """
        Generate element ID list and index dictionary from given list.
        :param list_in: list
        :return: (list, list_indices_map)
        """
        list_indices_map = {
            key: value for (key, value) in zip(list_in, range(0, len(list_in)))
        }
        return list_in, list_indices_map


class ModeShareHandler(PlanHandlerTool):
    """
    Extract Mode Share from Plans.
    """

    requirements = [
        'plans',
        'attributes',
        'transit_schedule',
        'output_config',
        'mode_map',
        'mode_hierarchy'
    ]
    valid_options = ['all']

    def __init__(self, config, option=None) -> None:
        """
        Initiate Handler.
        :param config: Config
        :param option: str, option
        """
        super().__init__(config, option)

        self.option = option  # todo options not implemented

        self.modes = None
        self.mode_indices = None
        self.classes = None
        self.class_indices = None
        self.activities = None
        self.activity_indices = None
        self.mode_counts = None
        self.results = None

        # Initialise results storage
        self.results = dict()  # Result geodataframes ready to export

    def __str__(self):
        return f'ModeShare'

    def build(self, resources: dict) -> None:
        """
        Build Handler.
        :param resources:
        :return:
        """
        super().build(resources)

        modes = self.resources['output_config'].modes + self.resources['transit_schedule'].modes
        if 'pt' in modes:
            modes.remove('pt')

        activities = self.resources['output_config'].activities
        sub_populations = self.resources['output_config'].sub_populations

        # Initialise mode classes
        self.modes, self.mode_indices = self.generate_id_map(modes)

        # Initialise class classes
        self.classes, self.class_indices = self.generate_id_map(
            sub_populations
        )

        # Initialise activity classes
        self.activities, self.activity_indices = self.generate_id_map(
            activities
        )

        # TODO - don't need to keep pt interactions or/for modeshare

        # Initialise mode count table
        self.mode_counts = np.zeros((len(self.modes),
                                    len(self.classes),
                                    len(self.activities),
                                    self.config.time_periods))

        self.results = dict()

    def process_plans(self, elem):
        """
        Iteratively aggregate 'vehicle enters traffic' and 'vehicle exits traffic'
        events to determine link volume counts.
        :param elem: Plan XML element
        """
        for plan in elem:
            if plan.get('selected') == 'yes':

                ident = elem.get('id')
                attribute_class = self.resources['attributes'].map.get(ident, 'not found')

                end_time = None
                modes = []

                for stage in plan:

                    if stage.tag == 'leg':
                        mode = stage.get('mode')
                        if mode == 'pt':
                            route = stage.xpath('route')[0].text.split('===')[-2]
                            mode = self.resources['transit_schedule'].mode_map.get(route)
                        modes.append(mode)

                    elif stage.tag == 'activity':
                        activity = stage.get('type')

                        if activity == 'pt interaction':  # ignore pt interaction activities
                            continue

                        # only add activity modes when there has been previous activity
                        # (ie trip start time)
                        if end_time:
                            mode = self.resources['mode_hierarchy'].get(modes)
                            x, y, z, w = self.table_position(
                                mode,
                                attribute_class,
                                activity,
                                end_time
                            )

                            self.mode_counts[x, y, z, w] += 1

                        # update endtime for next activity
                        end_time = convert_time(stage.get('end_time'))

                        # reset modes
                        modes = []

    def finalise(self):
        """
        Following plan processing, the raw mode share table will contain counts by mode,
        population attribute class, activity and period (where period is based on departure
        time).
        Finalise aggregates these results as required and creates a dataframe.
        """

        # Scale final counts
        self.mode_counts *= 1.0 / self.config.scale_factor

        names = ['mode', 'class', 'activity', 'hour']
        indexes = [self.modes, self.classes, self.activities, range(self.config.time_periods)]
        index = pd.MultiIndex.from_product(indexes, names=names)
        counts_df = pd.DataFrame(self.mode_counts.flatten(), index=index)[0]

        # mode counts breakdown output
        counts_df = counts_df.unstack(level='mode').sort_index()
        key = "mode_counts_{}_breakdown".format(self.option)
        self.results[key] = counts_df

        # mode counts totals output
        total_counts_df = counts_df.sum(0)
        key = "mode_counts_{}_total".format(self.option)
        self.results[key] = total_counts_df

        # convert to mode shares
        total = self.mode_counts.sum()

        # mode shares breakdown output
        key = "mode_shares_{}_breakdown".format(self.option)
        self.results[key] = counts_df / total

        # mode shares totals output
        key = "mode_shares_{}_total".format(self.option)
        self.results[key] = total_counts_df / total

    @staticmethod
    def generate_id_map(list_in):
        """
        Generate element ID list and index dictionary from given list.
        :param list_in: list
        :return: (list, list_indices_map)
        """
        if not len(set(list_in)) == len(list_in):
            raise UserWarning("non unique mode list found")

        list_indices_map = {
            key: value for (key, value) in zip(list_in, range(0, len(list_in)))
        }
        return list_in, list_indices_map

    def table_position(
        self,
        mode,
        attribute_class,
        activity,
        time
    ):
        """
        Calculate the result table coordinates from given maps.
        :param mode: String, mode id
        :param attribute_class: String, class id
        :param activity: String, activity id
        :param time: Timestamp of event
        :return: (x, y, z, w) tuple of integers to index results table
        """
        x = self.mode_indices[mode]
        y = self.class_indices[attribute_class]
        z = self.activity_indices[activity]
        w = floor(time / (86400.0 / self.config.time_periods)) % self.config.time_periods
        return x, y, z, w


class AgentLogsHandler(PlanHandlerTool):

    requirements = ['plans', 'transit_schedule']
    valid_options = ['all']

    # todo make it so that 'all' option not required (maybe for all plan handlers)

    def __init__(self, config, option=None):
        """
        Initiate handler.
        :param config: config
        :param option: str, mode option
        """

        super().__init__(config, option)

        self.option = option

        self.activities_log = None
        self.legs_log = None

        # Initialise results storage
        self.results = dict()  # Result dataframes ready to export

    def __str__(self):
        return f'LogHandler'

    def build(self, resources: dict) -> None:
        """
        Build handler from resources.
        :param resources: dict, supplier resources
        :return: None
        """
        super().build(resources)

        csv_name = "{}_activity_log_{}.csv".format(self.config.name, self.option)
        csv_path = os.path.join(self.config.output_path, csv_name)
        self.activities_log = ChunkWriter(csv_path)

        csv_name = "{}_leg_log_{}.csv".format(self.config.name, self.option)
        csv_path = os.path.join(self.config.output_path, csv_name)
        self.legs_log = ChunkWriter(csv_path)

    def process_plans(self, elem):

        """
        Build list of leg and activity logs (dicts) for each selected plan.

        Note that this assumes that first stage of a plan is ALWAYS an activity.
        Note that activity wrapping is not dealt with here.

        :return: Tuple[List[dict]]
        """
        for plan in elem:
            if plan.get('selected') == 'yes':

                activities = []
                legs = []

                ident = plan.getparent().get('id')

                leg_seq_idx = 0
                trip_seq_idx = 0
                act_seq_idx = 0

                arrival_dt = datetime.strptime("00:00:00", '%H:%M:%S')

                for stage in plan:

                    if stage.tag == 'activity':
                        act_seq_idx += 1

                        act_type = stage.get('type')

                        if not act_type == 'pt interaction':

                            trip_seq_idx += 1  # increment for a new trip idx

                            end = stage.get('end_time', '23:59:59')
                            end_dt = safe_strptime(end)

                            duration = end_dt - arrival_dt

                        else:
                            end_dt = arrival_dt  # zero duration
                            duration = arrival_dt - arrival_dt

                        x = stage.get('x')
                        y = stage.get('y')

                        activities.append(
                            {
                                'agent': ident,
                                'seq': act_seq_idx,
                                'act': act_type,
                                'x': x,
                                'y': y,
                                'start': arrival_dt.time(),
                                'end': end_dt.time(),
                                # 'duration': duration,
                                'start_s': self.get_seconds(arrival_dt),
                                'end_s': self.get_seconds(end_dt),
                                'duration_s': duration.total_seconds()
                            }
                        )

                    elif stage.tag == 'leg':
                        leg_seq_idx += 1

                        mode = stage.get('mode')
                        if mode == 'pt':
                            route = stage.xpath('route')[0].text.split('===')[-2]
                            mode = self.resources['transit_schedule'].mode_map.get(route)

                        trav_time = stage.get('trav_time')
                        h, m, s = trav_time.split(":")
                        td = timedelta(hours=int(h), minutes=int(m), seconds=int(s))

                        arrival_dt = end_dt + td

                        legs.append(
                            {
                                'agent': ident,
                                'seq': leg_seq_idx,
                                'trip': trip_seq_idx,
                                'mode': mode,
                                'ox': x,
                                'oy': y,
                                'dx': None,
                                'dy': None,
                                'start': end_dt.time(),
                                'end': arrival_dt.time(),
                                # 'duration': td,
                                'start_s': self.get_seconds(end_dt),
                                'end_s': self.get_seconds(arrival_dt),
                                'duration_s': td.total_seconds(),
                                'distance': stage.get('distance')
                            }
                        )

                # back-fill leg destinations
                for idx, leg in enumerate(legs):
                    leg['dx'] = activities[idx + 1]['x']
                    leg['dy'] = activities[idx + 1]['y']

                self.activities_log.add(activities)
                self.legs_log.add(legs)

    def finalise(self):
        """
        Finalise aggregates and joins these results as required and creates a dataframe.
        """

        self.activities_log.finish()
        self.legs_log.finish()

    @staticmethod
    def get_seconds(dt: datetime) -> int:
        """
        Extract time of day in seconds from datetime.
        :param dt: datetime
        :return: int, seconds
        """
        h = dt.hour
        m = dt.minute
        s = dt.second
        return s + (60 * (m + (60 * h)))


class AgentPlansHandler(PlanHandlerTool):
    """
    Write log of all plans, including selection and score.
    Format will we mostly duplicate of legs log.
    """

    requirements = ['plans', 'transit_schedule', 'attributes']
    # valid_options = ['all']

    def __init__(self, config, option=None):
        """
        Initiate handler.
        :param config: config
        :param option: str, mode option
        """

        super().__init__(config, option)

        self.option = option

        self.plans_log = None

        # Initialise results storage
        self.results = dict()  # Result dataframes ready to export

    def __str__(self):
        return f'ScoreHandler'

    def build(self, resources: dict) -> None:
        """
        Build handler from resources.
        :param resources: dict, supplier resources
        :return: None
        """
        super().build(resources)

        csv_name = "{}_scores_log_{}.csv".format(self.config.name, self.option)
        csv_path = os.path.join(self.config.output_path, csv_name)
        self.plans_log = ChunkWriter(csv_path)

    def process_plans(self, elem):

        """
        Build list of leg logs (dicts) for each selected plan.

        Note that this assumes that first stage of a plan is ALWAYS an activity.
        Note that activity wrapping is not dealt with here.

        :return: Tuple[List[dict]]
        """

        ident = elem.get('id')
        # get subpop
        subpop = self.resources['attributes'].map.get(ident)
        # todo is it slow calling a dict every time? Could keep these closer.

        if not subpop == self.option:
            return None

        for pidx, plan in enumerate(elem):

            selected = str(plan.get('selected'))
            score = float(plan.get('score'))

            activities = []
            legs = []
            leg_seq_idx = 0
            # trip_seq_idx = 0
            act_seq_idx = 0

            arrival_dt = datetime.strptime("00:00:00", '%H:%M:%S')

            for stage in plan:

                if stage.tag == 'activity':
                    act_seq_idx += 1

                    act_type = stage.get('type')

                    if not act_type == 'pt interaction':

                        # trip_seq_idx += 1  # increment for a new trip idx

                        end = stage.get('end_time', '23:59:59')
                        end_dt = safe_strptime(end)
                        duration = end_dt - arrival_dt

                    else:
                        end_dt = arrival_dt  # zero duration
                        duration = arrival_dt - arrival_dt

                    x = stage.get('x')
                    y = stage.get('y')

                    activities.append(
                        {
                            'agent': ident,
                            'pidx': pidx,
                            'score': score,
                            'selected': selected,
                            'stage_type': 'act',
                            # 'seq': act_seq_idx,
                            'type': act_type,
                            'ox': x,
                            'oy': y,
                            'dx': x,
                            'dy': y,
                            'start': arrival_dt.time(),
                            'end': end_dt.time(),
                            # 'duration': duration,
                            'start_s': self.get_seconds(arrival_dt),
                            'end_s': self.get_seconds(end_dt),
                            'duration_s': duration.total_seconds(),
                        }
                    )

                elif stage.tag == 'leg':
                    leg_seq_idx += 1

                    mode = stage.get('mode')
                    if mode == 'pt':
                        route = stage.xpath('route')[0].text.split('===')[-2]
                        mode = self.resources['transit_schedule'].mode_map.get(route)

                    trav_time = stage.get('trav_time')
                    h, m, s = trav_time.split(":")
                    td = timedelta(hours=int(h), minutes=int(m), seconds=int(s))

                    arrival_dt = end_dt + td

                    legs.append(
                        {
                            'agent': ident,
                            'pidx': pidx,
                            'score': score,
                            'selected': selected,
                            'stage_type': 'leg',
                            # 'seq': leg_seq_idx,
                            # 'trip': trip_seq_idx,
                            'type': mode,
                            'ox': x,
                            'oy': y,
                            'dx': None,
                            'dy': None,
                            'start': end_dt.time(),
                            'end': arrival_dt.time(),
                            # 'duration': td,
                            'start_s': self.get_seconds(end_dt),
                            'end_s': self.get_seconds(arrival_dt),
                            'duration_s': td.total_seconds(),
                            # 'distance': stage.get('distance'),
                        }
                    )

            # back-fill leg destinations
            for idx, leg in enumerate(legs):
                leg['dx'] = activities[idx + 1]['ox']
                leg['dy'] = activities[idx + 1]['oy']

            # combine into plan
            # todo make this less shit.
            assert len(activities) - len(legs) == 1

            plans_log = []
            for i in range(len(legs)):
                plans_log.append(activities[i])
                plans_log.append(legs[i])
            plans_log.append(activities[-1])

            self.plans_log.add(plans_log)

    def finalise(self):
        """
        Finalise aggregates and joins these results as required and creates a dataframe.
        """

        self.plans_log.finish()

    @staticmethod
    def get_seconds(dt: datetime) -> int:
        """
        Extract time of day in seconds from datetime.
        :param dt: datetime
        :return: int, seconds
        """
        h = dt.hour
        m = dt.minute
        s = dt.second
        return s + (60 * (m + (60 * h)))


class AgentHighwayDistanceHandler(PlanHandlerTool):
    """
    Extract modal distances from agent plans
    todo road only will not require transit schedule... maybe split road and pt
    """

    requirements = [
        'plans',
        'agents',
        'osm:ways'
        ]
    valid_options = ['car']

    def __init__(self, config, option=None):
        """
        Initiate handler.
        :param config: config
        :param option: str, mode option
        """
        super().__init__(config, option)

        self.option = option
        self.agents = None
        self.osm_ways = None

        self.agents_ids = None
        self.ways = None
        self.agent_indices = None
        self.ways_indices = None

        self.distances = None

        # Initialise results storage
        self.results = dict()  # Result dataframes ready to export

    def __str__(self):
        return f'AgentHighwayDistance)'

    def build(self, resources: dict) -> None:
        """
        Build Handler.
        :param resources: dict, resources from suppliers
        :return: None
        """
        super().build(resources)

        self.agents = resources['agents']
        self.osm_ways = resources['osm:ways']

        # Initialise agent indices
        self.agents_ids, self.agent_indices = self.generate_indices_map(self.agents.idents)

        # Initialise way indices
        self.ways, self.ways_indices = self.generate_indices_map(self.osm_ways.classes)

        # Initialise results array
        self.distances = np.zeros((len(self.agents_ids),
                                   len(self.ways)))

    def process_plans(self, elem):
        """
        Iteratively aggregate distance on highway distances from legs of selected plans.
        :param elem: Plan XML element
        """
        ident = elem.get('id')

        for plan in elem:
            if plan.get('selected') == 'yes':

                for stage in plan:

                    if stage.tag == 'leg':
                        mode = stage.get('mode')
                        if not mode == self.option:
                            continue

                        route = stage.xpath('route')[0].text.split(' ')
                        length = len(route)
                        for i, link in enumerate(route):
                            way = str(self.osm_ways.ways.get(link, None))
                            distance = float(self.osm_ways.lengths.get(link, 0))
                            if i == 0 or i == length - 1:  # halve first and last link lengths
                                distance /= 2

                            x, y = self.table_position(
                                ident,
                                way,
                            )

                            self.distances[x, y] += distance

    def finalise(self):
        """
        Following plan processing, the raw distance table will contain agent travel distance by way.
        Finalise aggregates and joins these results as required and creates a dataframe.
        """

        names = ['agent', 'way']
        indexes = [self.agents.idents, self.ways]
        index = pd.MultiIndex.from_product(indexes, names=names)
        distance_df = pd.DataFrame(self.distances.flatten(), index=index)[0]

        # mode counts breakdown output
        distance_df = distance_df.unstack(level='way').sort_index()

        # calculate agent total distance
        distance_df['total'] = distance_df.sum(1)

        # calculate summary
        total_df = distance_df.sum(0)
        key = "agent_distance_{}_total".format(self.option)
        self.results[key] = total_df

        # join with agent attributes
        key = "agent_distances_{}_breakdown".format(self.option)
        self.results[key] = distance_df.join(
            self.agents.attributes_df, how="left"
        )

    def table_position(
        self,
        ident,
        way
    ):
        """
        Calculate the result table coordinates from given maps.
        :param ident: String, agent id
        :param way: String, way id
        :return: (x, y) tuple of integers to index results table
        """
        x = self.agent_indices[ident]
        y = self.ways_indices[way]
        return x, y


class PlanHandlerWorkStation(WorkStation):
    """
    Work Station class for collecting and building Plans Handlers.
    """

    tools = {
        "mode_share": ModeShareHandler,
        "agent_logs": AgentLogsHandler,
        "agent_plans": AgentPlansHandler,
        "highway_distances": AgentHighwayDistanceHandler,
    }

    def build(self, spinner=None):
        """
        Build all required handlers, then finalise and save results.
        :return: None
        """

        if not self.resources:
            return None

        # build tools
        super().build(spinner)

        # iterate through plans
        plans = self.supplier_resources['plans']
        for i, person in enumerate(plans.persons):
            for event_handler in self.resources.values():
                event_handler.process_plans(person)
            if not i % 10000 and spinner:
                spinner.text = f'{self} processed {i} plans.'

        # finalise
        # Generate event file outputs
        for handler_name, handler in self.resources.items():
            if spinner:
                spinner.text = f'{self} finalising {handler_name}.'
            handler.finalise()
            # if self.config.contract:
            #     handler.contract_results()

            for name, result in handler.results.items():
                if spinner:
                    spinner.text = f'{self} writing {name} results to disk.'
                csv_name = "{}_{}.csv".format(self.config.name, name)
                csv_path = os.path.join(self.config.output_path, csv_name)

                # File exports
                result.to_csv(csv_path, header=True)

    def __str__(self):
        return f'Plan Handling WorkStation'


def convert_time(t: str) -> int:
    """
    Convert MATSim output plan times into seconds

    :param t: MATSim str time
    :return: seconds int
    """
    if not t:
        return None
    t = t.split(":")
    return ((int(t[0]) * 60) + int(t[1])) * 60 + int(t[2])


def export_geojson(gdf, path):
    """
    Given a geodataframe, export geojson representation to specified path.
    :param gdf: Input geodataframe
    :param path: Output path
    """
    with open(path, "w") as file:
        file.write(gdf.to_json())


def safe_strptime(time):
    try:
        dt = datetime.strptime(time, '%H:%M:%S')
    except ValueError:
        time = time.replace('24', '23')
        dt = datetime.strptime(time, "%H:%M:%S")
        dt += timedelta(hours=1)
    return dt
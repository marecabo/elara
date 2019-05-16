import pandas as pd
import os
import numpy as np


class Benchmarks:
    scores_df = None
    meta_score = None
    benchmarks = {}

    def __init__(self, config):
        """
        Wrapper for all benchmarks (ie Cordons ect). Scoring method extracts all
        benchmark scores and combines using weights into a Metascore.
        :param config: Config object
        """

        self.config = config

        for cordon_name in config.benchmarks:
            self.benchmarks[cordon_name] = BENCHMARK_MAP[cordon_name](
                cordon_name, config)

    def score(self):
        """
        Extract all sub scores from benchmarks and return combine 'metascore'.
        Writes summary of results to csv.
        :return: Float
        """
        scores = {}
        meta_score = 0
        for benchmark_name, benchmark in self.benchmarks.items():
            sub_scores = benchmark.output_and_score()
            scores[benchmark_name] = sub_scores

            # Combine with weights
            weight = BENCHMARK_WEIGHTS[benchmark_name]
            for s in sub_scores.values():
                meta_score += (s * weight)

        # Write scores
        scores_df = pd.DataFrame(scores).T
        csv_name = 'benchmark_scores.csv'
        csv_path = os.path.join(self.config.output_path, csv_name)
        scores_df.to_csv(csv_path)

        self.meta_score = meta_score
        self.scores_df = scores_df

        return meta_score


class IrelandCommuterStats:

    def __init__(self, name, config):
        pass


class DublinCanalCordon:

    cordon_counts = []
    benchmark_path = os.path.join('benchmark_data', 'ireland', 'dublin_cordon', 'InnerCordon2016.csv')
    cordon_path = os.path.join('benchmark_data', 'ireland', 'dublin_cordon', 'dublin_cordon.csv')

    def __init__(self, name, config):
        """
        Stats object for comparing output mode shares by population attribute to benchmark
        :param name:
        :param config:
        """
        pass


class Cordon:

    cordon_counts = []

    benchmark_path = None
    cordon_path = None

    directions = {'in': 1, 'out': 2}
    year = 2016
    hours = None
    modes = ['car']

    def __init__(self, name, config):
        """
        Cordon Object used for handling a cordon benchmark. Initiates two CordonCount
        objects (one for 'in' and one for 'out counts) with loaded counts and link map.
        :param name: String, cordon name
        :param config: Config
        """
        self.config = config
        counts_df = pd.read_csv(self.benchmark_path)
        links_df = pd.read_csv(self.cordon_path, index_col=0)

        if not self.hours:
            self.hours = range(self.config.time_periods)

        for direction_name, dir_code in self.directions.items():
            self.cordon_counts.append(CordonCount(
                name,
                config,
                self.year,
                self.hours,
                direction_name,
                dir_code,
                counts_df,
                links_df
            ))

    def output_and_score(self):
        """
        Builds paths for volume count outputs, loads and combines for scoring.
        Collects scoring from CordonCount objects.
        :return: Dictionary of scores {'in': float, 'out': float}
        """

        # Build paths and load appropriate volume counts
        results_dfs = {}
        for mode in self.modes:
            results_name = "{}_volume_counts_{}.csv".format(self.config.name, mode)
            results_path = os.path.join(self.config.output_path, results_name)
            results_df = pd.read_csv(results_path, index_col=0)
            results_df.index.name = 'link_id'
            select_cols = ['class'] + [str(i) for i in self.hours]
            results_df = results_df.loc[:, select_cols]
            results_dfs[mode] = results_df

        # get scores and write outputs
        scores = {}
        for cordon_count in self.cordon_counts:
            scores[cordon_count.direction] = cordon_count.output_and_score(results_dfs)
        return scores


class CordonCount:

    def __init__(self, name, config, year, hours, direction_name, dir_code, counts_df, links_df):
        """
        Builds list of link_ids and counts for gifven direction.
        :param name: String, name
        :param config: Config
        :param direction_name: String
        :param dir_code: Int
        :param counts_df: DataFrame of all counts for cordon
        :param links_df: DataFrame of cordon-count to links
        """
        self.cordon_name = name
        self.direction = direction_name
        self.config = config
        self.year = year
        self.hours = hours
        self.dir_code = dir_code
        self.counts_df = counts_df

        # Get cordon links
        self.link_ids = self.get_links(links_df, dir_code)

    def output_and_score(self, results_dfs):
        """
        Join all results from different volume counts (modal) and extract counts
        for cordon. Scoring is calculated by summing the absolute difference between
        hourly total counts and model results, then normalising by the total of all
        counts.
        :param results_dfs: DataFrame object of results
        :return: Float
        """
        # collect all results
        concat_df = pd.DataFrame()
        for mode, result_df in results_dfs.items():
            concat_df = pd.concat([concat_df, result_df.loc[result_df.index.isin(self.link_ids)]], axis=0)
        classes_df = concat_df.groupby('class').sum()

        # Build array for scoring
        results_array = np.array(classes_df.sum())

        # Label and write csv with counts by subpopulation
        classes_df['source'] = 'model'
        csv_name = '{}_{}_classes.csv'.format(self.cordon_name, self.direction)
        csv_path = os.path.join(self.config.output_path, csv_name)
        classes_df.to_csv(csv_path)

        # Get cordon counts for mode
        counts_array = self.get_counts(self.counts_df, modes=results_dfs.keys())
        count_df = self.counts_to_df(counts_array)

        # Label and write benchmark csv
        benchmark_df = pd.concat([count_df, classes_df]).groupby('source').sum()
        csv_name = '{}_{}_benchmark.csv'.format(self.cordon_name, self.direction)
        csv_path = os.path.join(self.config.output_path, csv_name)
        benchmark_df.to_csv(csv_path)

        # Calc score
        return 1 - (sum(np.absolute(results_array - counts_array)) / counts_array.sum())

    def get_links(self, links_df, direction_code):
        """
        Filter given DataFrame for direction.
        :param links_df: DataFrame
        :param direction_code: Int
        :return: DataFrame
        """
        df = links_df.loc[links_df.dir == direction_code, :]
        return list(set(df.link))

    def get_counts(self, counts_df, modes):
        """
        Builds array of total counts by hour.
        TODO could simplify but might add dict of counts by station in future
        :param counts_df: DataFrame
        :param modes: Strings
        :return:
        """
        counts_array = np.zeros(len(self.hours))

        df = counts_df.loc[counts_df.Year == self.year, :]
        assert(len(df)), f'No {self.cordon_name} benchmark counts left from after filtering by {self.year}'

        df = counts_df.loc[counts_df.Hour.isin(self.hours), :]
        assert(len(df)), f'No {self.cordon_name} benchmark counts left from after filtering by hours:{self.hours}'

        df = counts_df.loc[counts_df.Direction == self.dir_code, :]
        site_indexes = list(set(df.Site))

        for site_index in site_indexes:
            site_df = df.loc[df.Site == site_index, :]
            hour_counts = np.array(site_df.sort_values('Hour').loc[:, modes]).sum(axis=1)
            assert len(hour_counts) == len(self.hours), f'Not extracted the right amount of hours {self.hours}'

            counts_array += hour_counts

        return counts_array

    def counts_to_df(self, array):
        """
        Build counts dataframe from array for writing to csv
        :param array: np.array
        :return: DataFrame
        """
        col_names = [str(i) for i in self.hours]
        df = pd.DataFrame(array, index=col_names).T
        df['source'] = 'count'
        return df


class InnerCordonCar(Cordon):

    cordon_counts = []

    benchmark_path = os.path.join('benchmark_data', 'inner_cordon', 'InnerCordon2016.csv')
    cordon_path = os.path.join('benchmark_data', 'inner_cordon', 'cordon_links.csv')

    directions = {'in': 1, 'out': 2}
    year = 2016
    hours = None
    modes = ['car']


# maps of benchmarks to Classes and weights for scoring
BENCHMARK_MAP = {"inner_cordon_car": InnerCordonCar,
                 "dublin_canal_cordon_car": DublinCanalCordon}

BENCHMARK_WEIGHTS = {"inner_cordon_car": 1,
                     "dublin_canal_cordon_car": 1}

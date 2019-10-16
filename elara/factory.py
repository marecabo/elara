from typing import Dict, List, Union
from halo import Halo
import pandas as pd


# Define tools to be used by Sub Processes
class Tool:
    """
    Base tool class, defines basic behaviour for all tools at each Workstation.
    Values:
        .requirements: list, of requirements that that must be provided by suppliers.
        .options_enabled: bool, for if requirements should carry through manager options.
        .valid_options/.invalid_options: Optional lists for option validation at init.
        .resources: dict, of supplier resources collected with .build() method.

    Methods:
        .__init__(): instantiate and validate option.
        .get_requirements(): return tool requirements.
        .build(): check if requirements are met then build.
    """
    requirements = []
    options_enabled = False

    valid_options = None
    invalid_options = None

    resources = {}

    def __init__(
            self, config,
            option: Union[None, str] = None
    ) -> None:
        """
        Initiate a tool instance with optional option (ie: 'bus').
        :param option: optional option, typically assumed to be str
        """
        self.config = config
        self.option = self._validate_option(option)

    def get_requirements(self) -> Union[None, Dict[str, list]]:
        """
        Default return requirements of tool for given .option.
        Returns None if .option is None.
        :return: dict of requirements
        """
        if not self.requirements:
            return None

        if self.options_enabled:
            requirements = {req: [self.option] for req in self.requirements}
        else:
            requirements = {req: None for req in self.requirements}

        return requirements

    def build(
            self,
            resource: Dict[str, list],
    ) -> None:
        """
        Default build self.
        :param resource: dict, supplier resources
        :return: None
        """
        for requirement in convert_to_unique_keys(self.get_requirements()):
            if requirement not in list(resource):
                raise ValueError(f'Missing requirement @{self}: {requirement}')

        self.resources = resource

    def _validate_option(self, option: str) -> str:
        """
        Validate option based on .valid_options and .invalid_option if not None.
        Raises UserWarning if option is not in .valid_options or in .invalid_options.
        :param option: str
        :return: str
        """
        if self.valid_options:
            if option not in self.valid_options:
                raise UserWarning(f'Unsupported option: {option} at tool: {self}')
        if self.invalid_options:
            if option in self.invalid_options:
                raise UserWarning(f'Invalid option: {option} at tool: {self}')
        return option


class WorkStation:
    """
    Base Class for WorkStations.

    Values:
        .depth: int, depth of workstation in longest path search, used for ordering graph operation.
        .tools: dict, of available tools.
    """
    depth = 0
    tools = {}

    def __init__(self, config) -> None:
        """
        Instantiate WorkStation.
        :param config: Config object
        """
        self.config = config

        self.resources = {}
        self.requirements = {}
        self.managers = None
        self.suppliers = None
        self.supplier_resources = {}

    def connect(
            self,
            managers: Union[None, list],
            suppliers: Union[None, list]
    ) -> None:
        """
        Connect workstations to their respective managers and suppliers to form a DAG.
        Note that arguments should be provided as lists.
        :param managers: list of managers
        :param suppliers: list of suppliers
        :return: None
        """
        self.managers = managers
        self.suppliers = suppliers

    def display_string(self):
        managers, suppliers, tools = "-None-", "-None-", "-None-"
        if self.managers:
            managers = str([str(m) for m in list(self.managers)])
        if self.suppliers:
            suppliers = str([str(s) for s in list(self.suppliers)])
        if self.tools:
            tools = list(self.tools)

        return f"👉️ {self}:\n" \
               f"   ⛓  Managers: {managers}\n" \
               f"   🕸  Suppliers: {suppliers}\n" \
               f"   🔧 Tooling: {tools}\n"

    def engage(self) -> None:
        """
        Engage workstation, initiating required tools and getting their requirements.
        Note that initiated tools are mapped in .resources.
        Note that requirements are mapped as .requirements.
        Note that tool order is preserves as defined in Workstation.tools.
        :return: None
        """

        all_requirements = []

        # get manager requirements
        manager_requirements = self.gather_manager_requirements()

        if not self.tools:
            self.requirements = manager_requirements

        # init required tools
        # build new requirements from tools
        # loop tool first looking for matches so that tool order is preserved
        else:
            for tool_name, tool in self.tools.items():
                for manager_requirement, options in manager_requirements.items():
                    if manager_requirement == tool_name:
                        if options:
                            for option in options:
                                # init
                                key = str(tool_name) + ':' + str(option)
                                self.resources[key] = tool(self.config, option)
                                tool_requirements = self.resources[key].get_requirements()
                                all_requirements.append(tool_requirements)
                        else:
                            # init
                            key = str(tool_name)
                            self.resources[key] = tool(self.config)
                            tool_requirements = self.resources[key].get_requirements()
                            all_requirements.append(tool_requirements)

            self.requirements = combine_reqs(all_requirements)

            # Clean out unsupported options for tools that don't support options
            # todo: this sucks...
            # better catch option enabled tools at init but requires looking forward at suppliers
            #  before they are engaged or validated...
            if self.requirements:
                for req, options in self.requirements.items():
                    if self.suppliers and options:

                        for s in self.suppliers:
                            if s.tools:
                                for name, tool in s.tools.items():
                                    if req == name and not tool.options_enabled:
                                        self.requirements[name] = None

    def validate_suppliers(self) -> None:
        """
        Collects available tools from supplier workstations. Raises ValueError if suppliers have
        missing tools.
        :return: None
        """

        # gather supplier tools
        supplier_tools = {}
        if self.suppliers:
            for supplier in self.suppliers:
                if not supplier.tools:
                    continue
                supplier_tools.update(supplier.tools)

        # check for missing requirements
        missing = set(self.requirements) - set(supplier_tools)
        if missing:
            raise ValueError(
                f'Missing requirements: {missing} from suppliers: {self.suppliers}.'
            )

    def gather_manager_requirements(self) -> Dict[str, List[str]]:
        """
        Gather manager requirements.
        :return: dict of manager reqs, eg {a: [1,2], b:[1]}
        """
        reqs = []
        if self.managers:
            for manager in self.managers:
                reqs.append(manager.requirements)
        return combine_reqs(reqs)

    def build(self, spinner=None):
        """
        Gather resources from suppliers for current workstation and build() all resources in
        order of .resources map.
        :param: spinner: optional spinner for verbose behaviour.
        :return: None
        """

        # gather resources
        if self.suppliers:
            for supplier in self.suppliers:
                self.supplier_resources.update(supplier.resources)

        if self.resources:
            for tool_name, tool in self.resources.items():
                if spinner:
                    spinner.text = f"Building {tool_name}."
                tool.build(self.supplier_resources)

    def load_all_tools(self, option=None) -> None:
        """
        Method used for testing.
        Load all available tools into resources with given option.
        :param option: option, default None, must be valid for tools
        :return: NOne
        """
        for name, tool in self.tools.items():
            if option is None and tool.valid_options is not None:
                option = tool.valid_options[0]
            self.resources[name] = tool(self.config, option)


class ChunkWriter:
    """
    Extend a list of lines (dicts) that are saved to drive as csv once they reach a certain length.
    """

    def __init__(self, path, chunksize=1000) -> None:
        self.path = path
        self.chunksize = chunksize

        self.chunk = []
        self.idx = 0

    def add(self, lines: list) -> None:
        """
        Add a list of lines (dicts) to the chunk.
        If chunk exceeds chunksize, then write to disk.
        :param lines: list of dicts
        :return: None
        """
        self.chunk.extend(lines)
        if len(self.chunk) > self.chunksize:
            self.write()

    def write(self) -> None:
        """
        Convert chunk to dataframe and write to disk.
        :return: None
        """
        chunk_df = pd.DataFrame(self.chunk, index=range(self.idx, self.idx + len(self.chunk)))
        if not self.idx:
            chunk_df.to_csv(self.path)
            self.idx += len(self.chunk)
        else:
            chunk_df.to_csv(self.path, header=None, mode="a")
            self.idx += len(self.chunk)
        del chunk_df
        self.chunk = []

    def finish(self) -> None:
        self.write()


def build(start_node: WorkStation, verbose=False) -> list:
    """
    Main function for validating graph requirements, then initiating and building minimum resources.

    Stage1: Traverse graph from starting workstation to suppliers with depth-first search,
    marking workstations with possible longest path.

    Stage 2: Traverse graph with breadth-first search, prioritising shallowest nodes, sequentially
    initiating required workstation .tools as .resources and building .requirements.

    Stage 3: Traverse graph along same path but backward, gathering resources from suppliers at
    each workstation and building all own resources.

    Note that circular dependencies are not supported.

    Note that the function should be given the workstation with the initial/final requirements
    for the factory.

    :param start_node: starting workstation
    :param verbose: bool, verbose behaviour
    :return: list, sequence of visits for stages 2 (initiation and validation) and 3 (building)
    """

    # stage 1:
    with Halo(text="Initialising workflow graph...", spinner="dots") as spinner:

        if is_cyclic(start_node):
            raise UserWarning(f"Cyclic dependency found at {is_cyclic(start_node)}")
        if is_broken(start_node):
            raise UserWarning(f"Broken dependency found at {is_broken(start_node)}")

        build_graph_depth(start_node)

        spinner.stop_and_persist(symbol='✅'.encode('utf-8'), text="Workflow graph prepared.")

    if verbose:
        print("****************************** DAG ******************************")
        display_graph(start_node)
        print("*****************************************************************")

    # stage 2:
    visited = []
    queue = []
    queue.append(start_node)
    visited.append(start_node)

    while queue:
        current = queue.pop(0)
        with Halo(text="Engaging {current}...", spinner="dots") as spinner:
            current.engage()

            if current.suppliers:
                current.validate_suppliers()

                for supplier in order_by_distance(current.suppliers):
                    if supplier not in visited:
                        queue.append(supplier)
                        visited.append(supplier)

            spinner.succeed(f"{current} engaged and suppliers validated.")

    print('✅', "All Workstations initiated and validated.")

    # stage 3:
    sequence = visited
    return_queue = visited[::-1]
    visited = []
    while return_queue:
        current = return_queue.pop(0)
        with Halo(text=f"Building {current}...", spinner="dots") as spinner:
            current.build(spinner)
            visited.append(current)
            spinner.succeed(f"{current} build completed.")

    print('✅', "All complete.")

    # return full sequence for testing
    return sequence + visited


def is_cyclic(start):
    """
    Return WorkStation if the directed graph starting at WorkStation has a cycle.
    :param start: starting WorkStation
    :return: WorkStation
    """
    path = set()
    visited = set()

    def visit(vertex):
        if vertex in visited:
            return False
        visited.add(vertex)
        path.add(vertex)
        if vertex.suppliers:
            for supplier in vertex.suppliers:
                if supplier in path or visit(supplier):
                    return supplier
        path.remove(vertex)

    return visit(start)


def is_broken(start):
    """
    Return WorkStation if directed graph starting at WorkStation has broken connection,
    ie a supplier who does not have the correct manager in .managers.
    :param start: starting WorkStation
    :return: WorkStation
    """

    visited = set()

    def broken_link(manager, supplier):
        if not supplier.managers:
            return True
        if manager not in supplier.managers:
            return True

    def visit(vertex):
        visited.add(vertex)
        if vertex.suppliers:

            for supplier in vertex.suppliers:
                if supplier in visited:
                    continue
                if broken_link(vertex, supplier) or visit(supplier):
                    return supplier

    return visit(start)


def build_graph_depth(node: WorkStation, visited=None, depth=0) -> list:
    """
    Function to recursive depth-first traverse graph of suppliers, recording workstation depth in
    graph.
    :param node: starting workstation
    :param visited: list, visited workstations
    :param depth: current depth
    :return: list, visited workstations in order
    """
    if not visited:
        visited = []
    visited.append(node)

    # Recur for all the nodes supplying this node
    if node.suppliers:
        depth = depth + 1
        for supplier in node.suppliers:
            if supplier.depth < depth:
                supplier.depth = depth
            build_graph_depth(supplier, visited, depth)

    return visited


def display_graph(node: WorkStation) -> None:
    """
    Function to depth first traverse graph from start vertex, displaying vertex connections
    :param node: starting Workstation
    :return: None
    """

    visited = set()

    def visit(vertex):
        print(vertex.display_string())
        visited.add(vertex)
        if vertex.suppliers:
            for supplier in vertex.suppliers:
                if supplier not in visited:
                    visit(supplier)

    visit(node)


def order_by_distance(candidates: list) -> list:
    """
    Returns candidate list ordered by .depth.
    :param candidates: list, of workstations
    :return: list, of workstations
    """
    return sorted(candidates, key=lambda x: x.depth, reverse=False)


def combine_reqs(reqs: List[dict]) -> Dict[str, list]:
    """
    Helper function for combining lists of requirements (dicts of lists) into a single
    requirements dict:

    [{req1:[a,b], req2:[b]}, {req1:[a], req2:[a], req3:None}] -> {req1:[a,b], req2:[a,b], req3:None}

    Note that no requirements are returned as an empty dict.

    Note that no options are returned as None ie {requirment: None}
    :param reqs: list of dicts of lists
    :return: dict, of requirements
    """
    if not reqs:
        return {}
    tool_set = set()
    for req in reqs:
        if req:
            tool_set.update(list(req))
    combined_reqs = {}
    for tool in tool_set:
        if tool_set:
            options = set()
            for req in reqs:
                if req and req.get(tool):
                    options.update(req[tool])
            if options:
                combined_reqs[tool] = list(options)
            else:
                combined_reqs[tool] = None
    return combined_reqs


def convert_to_unique_keys(d: dict) -> list:
    """
    Helper function to convert a requirements dictionary into a list of unique keys:

    {req1:[a,b], req2:[a], req3:None} -> ['req1:a', 'req1:b', 'req2:a', 'req3'}

    Note that if option is None, key will be returned as requirement key only.

    :param d: dict, of requirements
    :return: list
    """
    keys = []
    if not d:
        return []
    for name, options in d.items():
        if not options:
            keys.append(name)
            continue
        for option in options:
            keys.append(f'{name}:{option}')
    return keys


def list_equals(l1, l2):
    """
    Helper function to check for equality between two lists of options.
    :param l1: list
    :param l2: list
    :return: bool
    """
    if l1 is None:
        if l2 is None:
            return True
        return False
    if not len(l1) == len(l2):
        return False
    if not sorted(l1) == sorted(l2):
        return False
    return True


def equals(d1, d2):
    """
    Helper function to check for equality between two dictionaries of requirements.
    :param d1: dict
    :param d2: dict
    :return: bool
    """
    if not list_equals(list(d1), list(d2)):
        return False
    for d1k, d1v, in d1.items():
        if not list_equals(d1v, d2[d1k]):
            return False
    return True
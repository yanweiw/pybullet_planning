from __future__ import print_function

import random
from itertools import product

import numpy as np
import math
import pybullet as p
from pprint import pprint

from .pr2_utils import draw_viewcone, get_viewcone, get_group_conf, set_group_conf, get_other_arm, \
    get_carry_conf, set_arm_conf, open_arm, close_arm, arm_conf, REST_LEFT_ARM

from .utils import unit_pose, get_collision_data, get_links, LockRenderer, \
    set_pose, get_movable_joints, draw_pose, pose_from_pose2d, set_velocity, set_joint_states, get_bodies, \
    flatten, INF, inf_generator, get_time_step, get_all_links, get_visual_data, pose2d_from_pose, multiply, invert, \
    get_sample_fn, pairwise_collisions, sample_placement, is_placement, aabb_contains_point, point_from_pose, \
    aabb2d_from_aabb, is_center_stable, aabb_contains_aabb, get_model_info, get_name, get_pose, dump_link, \
    dump_joint, dump_body, PoseSaver, get_aabb, add_text, GREEN, AABB, remove_body, HideOutput, \
    stable_z, Pose, Point, create_box, load_model, get_joints, set_joint_position, BROWN, Euler, PI, \
    set_camera_pose, TAN, RGBA, sample_aabb, get_min_limit, get_max_limit, get_joint_position, get_joint_name, \
    euler_from_quat, get_client, JOINT_TYPES, get_joint_type, get_link_pose, get_closest_points, \
    body_collision, is_placed_on_aabb, joint_from_name, body_from_end_effector, flatten_links, \
    get_link_subtree, quat_from_euler, euler_from_quat, create_box, set_pose, Pose, Point, get_camera_matrix


OBJ = '?obj'

BASE_LINK = 'base_link'
BASE_JOINTS = ['x', 'y', 'theta']
BASE_VELOCITIES = np.array([1., 1., math.radians(180)]) / 1. # per second
BASE_RESOLUTIONS = np.array([0.05, 0.05, math.radians(10)])

zero_limits = 0 * np.ones(2)
half_limits = 12 * np.ones(2)
BASE_LIMITS = (-half_limits, +half_limits) ## (zero_limits, +half_limits) ##
BASE_LIMITS = ((-1, 3), (6, 13))

CAMERA_FRAME = 'high_def_optical_frame'
EYE_FRAME = 'wide_stereo_gazebo_r_stereo_camera_frame'
CAMERA_MATRIX = get_camera_matrix(width=640, height=480, fx=525., fy=525.) # 319.5, 239.5 | 772.55, 772.5

def set_pr2_ready(pr2, arm='left', grasp_type='top', DUAL_ARM=False):
    other_arm = get_other_arm(arm)
    if not DUAL_ARM:
        initial_conf = get_carry_conf(arm, grasp_type)
        set_arm_conf(pr2, arm, initial_conf)
        open_arm(pr2, arm)
        set_arm_conf(pr2, other_arm, arm_conf(other_arm, REST_LEFT_ARM))
        close_arm(pr2, other_arm)
    else:
        for a in [arm, other_arm]:
            initial_conf = get_carry_conf(a, grasp_type)
            set_arm_conf(pr2, a, initial_conf)
            open_arm(pr2, a)

def load_asset(obj, **kwargs):
    from world_builder.utils import load_asset as helper
    return helper(obj, **kwargs)


def add_body(body, pose=unit_pose()):
    set_pose(body, pose)
    return body


def Pose2d(x=0., y=0., yaw=0.):
    return np.array([x, y, yaw])


def place_body(body, pose2d=Pose2d(), z=None):
    if z is None:
        lower, upper = body.get_aabb()
        z = -lower[2]
        # z = stable_z_on_aabb(body, region) # TODO: don't worry about epsilon differences
    return add_body(body, pose_from_pose2d(pose2d, z=z))


def load_texture(path):
    import pybullet
    return pybullet.loadTexture(path)


#######################################################

def set_zero_state(body, zero_pose=True, zero_conf=True):
    if zero_pose:
        set_pose(body, unit_pose())
        set_velocity(body, *unit_pose())
    if zero_conf:
        joints = get_movable_joints(body)
        # set_joint_positions(body, joints, np.zeros(len(joints)))
        set_joint_states(body, joints, np.zeros(len(joints)), np.zeros(len(joints)))


def set_zero_world(bodies=None, **kwargs):
    if bodies is None:
        bodies = get_bodies()
    for body in bodies:
        set_zero_state(body, **kwargs)


def write_yaml():
    raise NotImplementedError()


def draw_pose2d(pose2d, z=0., **kwargs):
    return draw_pose(pose_from_pose2d(pose2d, z=z), **kwargs)


def draw_pose2d_path(path, z=0., **kwargs):
    # TODO: unify with open-world-tamp, namo, etc.
    # return list(flatten(draw_point(np.append(pose2d[:2], [z]), **kwargs) for pose2d in path))
    return list(flatten(draw_pose2d(pose2d, z=z, **kwargs) for pose2d in path))


def get_indices(sequence):
    return range(len(sequence))


def clip_delta(difference, max_velocities, time_step):
    # TODO: self.max_delta
    durations = np.divide(np.absolute(difference), max_velocities)
    max_duration = np.linalg.norm(durations, ord=INF)
    if max_duration == 0.:
        return np.zeros(len(difference))
    return min(max_duration, time_step) / max_duration * np.array(difference)


def sample_bernoulli_step(events_per_sec, time_step):
    p_event = events_per_sec * time_step
    return random.random() <= p_event


def constant_controller(value):
    return (value for _ in inf_generator())


def timeout_controller(controller, timeout=INF, time_step=None):
    if time_step is None:
        time_step = get_time_step()
    time_elapsed = 0.
    for output in controller:
        if time_elapsed > timeout:
            break
        yield output
        time_elapsed += time_step


def set_collisions(body1, enable=False):
    import pybullet
    # pybullet.setCollisionFilterGroupMask()
    for body2 in get_bodies():
        for link1, link2 in product(get_all_links(body1), get_all_links(body2)):
            pybullet.setCollisionFilterPair(body1, body2, link1, link2, enable)


def get_color(body):  # TODO: unify with open-world-tamp
    # TODO: average over texture
    visual_data = get_visual_data(body)
    if not visual_data:
        # TODO: no viewer implies no visual data
        return None
    return visual_data[0].rgbaColor


def multiply2d(*pose2ds):
    poses = list(map(pose_from_pose2d, pose2ds))
    return pose2d_from_pose(multiply(*poses))


def invert2d(pose2d):
    # return -np.array(pose2d)
    return pose2d_from_pose(invert(pose_from_pose2d(pose2d)))


def project_z(point, z=2e-3):
    return np.append(point[:2], [z])


#######################################################

MIN_DISTANCE = 1e-2


def sample_conf(robot, obstacles=[], min_distance=MIN_DISTANCE):
    sample_fn = get_sample_fn(robot, robot.joints, custom_limits=robot.custom_limits)
    while True:
        conf = sample_fn()
        robot.set_positions(conf)
        if not pairwise_collisions(robot, obstacles, max_distance=min_distance):
            return conf


def sample_safe_placement(obj, region, obstacles=[], min_distance=MIN_DISTANCE):
    obstacles = set(obstacles) - {obj, region}
    while True:
        pose = sample_placement(obj, region)
        if pose is None:
            break
        if not pairwise_collisions(obj, obstacles, max_distance=min_distance):
            set_pose(obj, pose)
            return pose


def check_placement(obj, region):
    return is_center_stable(obj, region, above_epsilon=INF, below_epsilon=INF)  # is_center_stable | is_placement


def is_on(obj_aabb, region_aabb):
    return aabb_contains_aabb(aabb2d_from_aabb(obj_aabb), aabb2d_from_aabb(region_aabb))


def is_above(robot, aabb):
    # return is_center_stable(robot, self.button)
    return aabb_contains_point(point_from_pose(robot.get_pose())[:2], aabb2d_from_aabb(aabb))


#######################################################

def nice_float(ele):
    if isinstance(ele, int) or ele.is_integer():
        return int(ele)
    else:
        return round(ele, 3)


def nice_tuple(tup):
    new_tup = []
    for ele in tup:
        new_tup.append(nice_float(ele))
    return tuple(new_tup)


def nice(tuple_of_tuples):
    ## float, int
    if isinstance(tuple_of_tuples, float):
        return nice_float(tuple_of_tuples)

    ## position, pose
    elif isinstance(tuple_of_tuples[0], tuple):

        ## pose = point + euler -> (x, y, z, yaw)
        if len(tuple_of_tuples[0]) == 3 and len(tuple_of_tuples[1]) == 4:
            return pose_to_xyzyaw(tuple_of_tuples)

        new_tuple = []
        for tup in tuple_of_tuples:
            new_tuple.append(nice_tuple(tup))
        return tuple(new_tuple)

    ## AABB
    elif isinstance(tuple_of_tuples, AABB):
        lower, upper = tuple_of_tuples
        return AABB(nice_tuple(lower), nice_tuple(upper))

    ## point, euler, conf
    return nice_tuple(tuple_of_tuples)


#######################################################

OBJ_SCALES = {
    'OilBottle': 0.25, 'VinegarBottle': 0.25, 'Salter': 0.1, 'Knife': 0.1, 'Fork': 0.2,
    'Microwave': 0.7, 'Pan': 0.3, 'Pot': 0.3, 'Kettle': 0.3,
    'Egg': 0.1, 'Veggie': 0.3, 'VeggieLeaf': 0.3, 'VeggieStem': 0.3,
    'MilkBottle': 0.2, 'Toaster': 0.2, 'Bucket': 0.7, 'Cart': 1.1,
    'PotBody': 0.3, 'BraiserBody': 0.37, 'BraiserLid': 0.37, 'Faucet': 0.35,
    'VeggieCabbage': 0.005, 'MeatTurkeyLeg': 0.0007, 'VeggieTomato': 0.005,
    'VeggieZucchini': 0.016, 'VeggiePotato': 0.015, 'VeggieCauliflower': 0.008,
    'VeggieGreenPepper': 0.0003, 'VeggieArtichoke': 0.017, 'MeatChicken': 0.0008,
}
OBJ_SCALES = {k.lower(): v * 0.7 for k, v in OBJ_SCALES.items()}
OBJ_YAWS = {
    'Microwave': PI, 'Toaster': PI / 2
}


def sample_pose(obj, aabb, obj_aabb=None, yaws=OBJ_YAWS):
    ## sample a pose in aabb that can fit an object in
    if obj_aabb != None:
        lower, upper = obj_aabb
        diff = [(upper[i] - lower[i]) / 2 for i in range(3)]
        lower = [aabb[0][i] + diff[i] for i in range(3)]
        upper = [aabb[1][i] - diff[i] for i in range(3)]
        aabb = AABB(lower=lower, upper=upper)
    x, y, z = sample_aabb(aabb)

    ## use pre-defined yaws for appliances like microwave
    if obj in yaws:
        yaw = yaws[obj]
    else:
        yaw = np.random.uniform(0, PI)

    return x, y, z, yaw


def sample_obj_on_body_link_surface(obj, body, link, scales=OBJ_SCALES, PLACEMENT_ONLY=False, max_trial=8):
    aabb = get_aabb(body, link)
    # x, y, z, yaw = sample_pose(obj, aabb)
    # maybe = load_asset(obj, x=round(x, 1), y=round(y, 1), yaw=yaw, floor=(body, link), scale=scales[obj], maybe=True)
    # sample_placement(maybe, body, bottom_link=link)

    x, y, z, yaw = sample_pose(obj, aabb)
    if isinstance(obj, str):
        obj = obj.lower()
        maybe = load_asset(obj, x=round(x, 1), y=round(y, 1), yaw=yaw, floor=(body, link), scale=scales[obj],
                           maybe=True)
    else:
        maybe = obj
    trial = 0
    while not aabb_contains_aabb(aabb2d_from_aabb(get_aabb(maybe)), aabb2d_from_aabb(aabb)):
        x, y, z, yaw = sample_pose(obj, aabb, get_aabb(maybe))
        if isinstance(obj, str):
            remove_body(maybe)
            maybe = load_asset(obj, x=round(x, 1), y=round(y, 1), yaw=yaw, floor=(body, link), scale=scales[obj],
                               maybe=True)
        else:
            pose = Pose(point=Point(x=x, y=y, z=z), euler=Euler(yaw=yaw))
            set_pose(maybe, pose)
        # print(f'sampling surface for {body}-{link}', nice(aabb2d_from_aabb(aabb)))
        trial += 1
        if trial > max_trial: break

    if isinstance(obj, str):
        remove_body(maybe)
        maybe = load_asset(obj, x=round(x, 1), y=round(y, 1), yaw=yaw, floor=(body, link), scale=scales[obj],
                           moveable=True)
    if PLACEMENT_ONLY: return x, y, z, yaw

    # print(nice(aabb2d_from_aabb(aabb)))
    # print(nice(aabb2d_from_aabb(get_aabb(maybe))))
    return maybe


def sample_obj_in_body_link_space(obj, body, link=None, scales=OBJ_SCALES,
                                  PLACEMENT_ONLY=False, XY_ONLY=False, verbose=False):
    aabb = get_aabb(body, link)
    x, y, z, yaw = sample_pose(obj, aabb)
    if isinstance(obj, str):
        obj = obj.lower()
        maybe = load_asset(obj, x=round(x, 1), y=round(y, 1), yaw=yaw, z=round(z, 1), scale=scales[obj], maybe=True)
    else:
        maybe = obj

    def contained(maybe):
        if not XY_ONLY:
            return aabb_contains_aabb(get_aabb(maybe), aabb)
        return aabb_contains_aabb(aabb2d_from_aabb(get_aabb(maybe)), aabb2d_from_aabb(aabb))

    while not contained(maybe) or body_collision(body, maybe, link1=link):
        x, y, z, yaw = sample_pose(obj, aabb, get_aabb(maybe))
        if isinstance(obj, str):
            remove_body(maybe)
            maybe = load_asset(obj, x=round(x, 1), y=round(y, 1), yaw=yaw, z=round(z, 1), scale=scales[obj], maybe=True)
        else:
            pose = Pose(point=Point(x=x, y=y, z=z), euler=Euler(yaw=yaw))
            set_pose(maybe, pose)
        if verbose:
            print(f'sampling space for {body}-{link} {nice(aabb)} : {obj} {nice(get_aabb(maybe))}', )

    ## lower the object until collision
    for interval in [0.1, 0.05, 0.01, 0.001]:
        while aabb_contains_aabb(get_aabb(maybe), aabb) and not body_collision(body, maybe, link1=link):
            z -= interval
            pose = Pose(point=Point(x=x, y=y, z=z), euler=Euler(yaw=yaw))
            set_pose(maybe, pose)
            if verbose:
                print(f'trying pose (int={interval}) for {obj}: z={z}')
        z += interval
    # z -= interval
    if verbose:
        print(f'   collision between {body}-{link} and {maybe}: {body_collision(body, maybe, link1=link)}')

    if isinstance(obj, str):
        remove_body(maybe)
        maybe = load_asset(obj, x=round(x, 1), y=round(y, 1), yaw=yaw, z=round(z, 1), scale=scales[obj], moveable=True)
    if PLACEMENT_ONLY: return x, y, z, yaw
    # print(nice(aabb2d_from_aabb(aabb)))
    # print(nice(aabb2d_from_aabb(get_aabb(maybe))))
    return maybe


def add_attachment(state=None, obj=None, parent=-1, parent_link=None, attach_distance=0.1):
    new_attachments = {}
    if state != None:
        new_attachments = dict(state.attachments)

    if parent == -1:  ## use robot as parent
        parent = state.robot
        link1 = None
        parent_link = state.robot.base_link
    else:
        link1 = parent_link

    joint = None
    if isinstance(obj, tuple):
        BODY_TO_OBJECT = state.world.BODY_TO_OBJECT
        link1 = BODY_TO_OBJECT[obj].handle_link
        obj, joint = obj

    collision_infos = get_closest_points(parent, obj, link1=link1, max_distance=INF)
    min_distance = min([INF] + [info.contactDistance for info in collision_infos])
    if attach_distance == None or (min_distance < attach_distance):  ## (obj not in new_attachments) and
        if joint != None:
            attachment = create_attachment(parent, parent_link, obj,
                                           child_link=link1, child_joint=joint)
        else:
            attachment = create_attachment(parent, parent_link, obj)
        new_attachments[obj] = attachment  ## may overwrite older attachment
    return new_attachments


def create_attachment(parent, parent_link, child, child_link=None, child_joint=None, OBJ=False):
    parent_link_pose = get_link_pose(parent, parent_link)
    child_pose = get_pose(child)
    grasp_pose = multiply(invert(parent_link_pose), child_pose)
    if OBJ:  ## attachment between objects
        return ObjAttachment(parent, parent_link, grasp_pose, child)
    return Attachment(parent, parent_link, grasp_pose, child,
                      child_link=child_link, child_joint=child_joint)


class Attachment(object):
    def __init__(self, parent, parent_link, grasp_pose, child,
                 child_joint=None, child_link=None):
        self.parent = parent  # TODO: support no parent
        self.parent_link = parent_link
        self.grasp_pose = grasp_pose
        self.child = child
        self.child_joint = child_joint
        self.child_link = child_link

    @property
    def bodies(self):
        return flatten_links(self.child) | flatten_links(self.parent, get_link_subtree(
            self.parent, self.parent_link))

    def assign(self):
        from .pr2_streams import LINK_POSE_TO_JOINT_POSITION
        # robot_base_pose = self.parent.get_positions(roundto=3)
        # robot_arm_pose = self.parent.get_positions(joint_group='left', roundto=3)  ## only left arm for now
        parent_link_pose = get_link_pose(self.parent, self.parent_link)
        child_pose = body_from_end_effector(parent_link_pose, self.grasp_pose)
        if self.child_link == None:
            set_pose(self.child, child_pose)
        elif self.child in LINK_POSE_TO_JOINT_POSITION:  ## pull drawer handle
            # for key in [robot_base_pose, robot_arm_pose]:
            for group in ['base', 'left']:
                key = self.parent.get_positions(joint_group=group, roundto=3)
                if key in LINK_POSE_TO_JOINT_POSITION[self.child][self.child_joint]:
                    position = LINK_POSE_TO_JOINT_POSITION[self.child][self.child_joint][key]
                    set_joint_position(self.child, self.child_joint, position)
                    # print(f'bullet.utils | Attachment | robot {key} @ {key} -> position @ {position}')
        return child_pose

    def apply_mapping(self, mapping):
        self.parent = mapping.get(self.parent, self.parent)
        self.child = mapping.get(self.child, self.child)

    def __repr__(self):
        name = self.__class__.__name__
        if self.child_link == None:
            return '{}({},{})'.format(name, self.parent, self.child)
        else:
            return '{}({},{}-{})'.format(name, self.parent, self.child, self.child_link)


def remove_attachment(state, obj=None):
    # print('bullet.utils | remove_attachment | old', state.attachments)
    if isinstance(obj, tuple): obj = obj[0]
    new_attachments = dict(state.attachments)
    if obj in new_attachments:
        new_attachments.pop(obj)
    # print('bullet.utils | remove_attachment | new', new_attachments)
    return new_attachments


class ObjAttachment(Attachment):
    def assign(self):
        parent_link_pose = get_link_pose(self.parent, self.parent_link)
        child_pose = body_from_end_effector(parent_link_pose, self.grasp_pose)
        set_pose(self.child, child_pose)

    # def __init__(self, parent, parent_link, child, rel_pose=None):
    #     super(ObjAttachment, self).__init__(parent, parent_link, None, child)
    #     if rel_pose == None:
    #         p_parent = get_link_pose(parent, parent_link)
    #         p_child= get_pose(child)
    #         rel_pose = (p_child[0][i] - p_parent[0][i] for i in range(len(p_child[0])))
    #     self.rel_pose = rel_pose
    # def assign(self):
    #     p_parent = get_link_pose(self.parent, self.parent_link)
    #     _, r_child = get_pose(self.child)
    #     p_child = (p_parent[0][i] + self.rel_pose[i] for i in range(len(self.rel_pose)))
    #     set_pose(self.child, (p_child, r_child))


#######################################################

def set_camera_target_body(body, link=None, dx=3.8, dy=0, dz=1):
    # if isinstance(body, tuple):
    #     link = BODY_TO_OBJECT[body].handle_link
    #     body = body[0]
    aabb = get_aabb(body, link)
    x = (aabb.upper[0] + aabb.lower[0]) / 2
    y = (aabb.upper[1] + aabb.lower[1]) / 2
    z = (aabb.upper[2] + aabb.lower[2]) / 2
    set_camera_pose(camera_point=[x + dx, y + dy, z + dz], target_point=[x, y, z])


def set_default_camera_pose():
    ## the whole kitchen & living room area
    # set_camera_pose(camera_point=[9, 8, 9], target_point=[6, 8, 0])

    ## just the kitchen
    set_camera_pose(camera_point=[4, 7, 4], target_point=[3, 7, 2])


def set_camera_target_robot(robot, distance=5, FRONT=False):
    x, y, yaw = get_pose2d(robot)
    target_point = (x, y, 2)
    yaw -= math.pi / 2
    pitch = - math.pi / 3
    if FRONT:
        yaw += math.pi
        pitch = -math.pi / 4  ## 0
        target_point = (x, y, 1)
    CLIENT = get_client()
    p.resetDebugVisualizerCamera(distance, math.degrees(yaw), math.degrees(pitch),
                                 target_point, physicsClientId=CLIENT)


#######################################################

# def summarize_links(body):
#     joints = get_joints(body)
#     for joint in joints:
#         check_joint_state(body, joint)
def get_point_distance(p1, p2):
    if isinstance(p1, tuple): p1 = np.asarray(p1)
    if isinstance(p2, tuple): p2 = np.asarray(p2)
    return np.linalg.norm(p1 - p2)


def get_pose2d(robot):
    point, quat = robot.get_pose()
    x, y, _ = point
    _, _, yaw = euler_from_quat(quat)
    return x, y, yaw


def summarize_joints(body):
    joints = get_joints(body)
    for joint in joints:
        check_joint_state(body, joint, verbose=True)


def check_joint_state(body, joint, verbose=False):
    name = get_joint_name(body, joint)
    pose = get_joint_position(body, joint)
    min_limit = get_min_limit(body, joint)
    max_limit = get_max_limit(body, joint)
    moveable = joint in get_movable_joints(body)
    joint_type = JOINT_TYPES[get_joint_type(body, joint)]

    category = 'fixed'
    state = None
    if min_limit < max_limit:

        if joint_type == 'revolute' and min_limit == 0:
            category = 'door-max'
            if pose == max_limit:
                state = 'door OPENED fully'
            elif pose == min_limit:
                state = 'door CLOSED'
            else:
                state = 'door OPENED partially'

        elif joint_type == 'revolute' and max_limit == 0:
            category = 'door-min'
            if pose == min_limit:
                state = 'door OPENED fully'
            elif pose == max_limit:
                state = 'door CLOSED'
            else:
                state = 'door OPENED partially'

        ## switch on faucet, machines
        elif joint_type == 'revolute' and min_limit + max_limit == 0:
            category = 'switch'
            if pose == min_limit:
                state = 'switch TURNED OFF'
            elif pose == max_limit:
                state = 'switch TURNED ON'

        elif joint_type == 'prismatic':  ## drawers
            category = 'drawer'
            if pose == max_limit:
                state = 'drawer OPENED fully'
            elif pose == min_limit:
                state = 'drawer CLOSED'
            else:
                state = 'drawer OPENED partially'

    else:
        state = 'fixed joint'

    if verbose:
        print(
            f'   joint {name}, pose = {pose}, limit = {nice((min_limit, max_limit))}, state = {state}, moveable = {moveable}')
    return category, state


def toggle_joint(body, joint):
    category, state = check_joint_state(body, joint)
    if 'OPENED' in state:
        close_joint(body, joint)
    elif 'CLOSED' in state:
        open_joint(body, joint)


def open_joint(body, joint, extent=0.8, pstn=None):
    if pstn == None:
        if isinstance(joint, str):
            joint = joint_from_name(body, joint)
        min_limit = get_min_limit(body, joint)
        max_limit = get_max_limit(body, joint)
        category, state = check_joint_state(body, joint)
        if category == 'door-max':
            pstn = max_limit * extent
        elif category == 'door-min':
            pstn = min_limit * extent
        elif category == 'drawer':
            pstn = max_limit
    set_joint_position(body, joint, pstn)


def close_joint(body, joint):
    min_limit = get_min_limit(body, joint)
    max_limit = get_max_limit(body, joint)
    category, state = check_joint_state(body, joint)
    if category == 'door-max':
        set_joint_position(body, joint, min_limit)
    elif category == 'door-min':
        set_joint_position(body, joint, max_limit)
    elif category == 'drawer':
        set_joint_position(body, joint, min_limit)


#######################################################

def get_readable_list(lst, world=None, NAME_ONLY=False):
    to_print = []
    for word in lst:
        if world != None and word in world.BODY_TO_OBJECT:  ## isinstance(word, int) and
            if NAME_ONLY:
                to_print.append(f'{world.BODY_TO_OBJECT[word].name}')
            else:
                to_print.append(f'{world.BODY_TO_OBJECT[word].debug_name}')
        else:
            to_print.append(word)
    return to_print


def summarize_facts(facts, world=None, name='Initial facts'):
    from pybullet_tools.logging import myprint as print
    print('----------------')
    print(f'{name} ({len(facts)})')
    predicates = {}
    for fact in facts:
        pred = fact[0].lower()
        if pred not in predicates:
            predicates[pred] = []
        predicates[pred].append(fact)
    predicates = {k: v for k, v in sorted(predicates.items())}
    # predicates = {k: v for k, v in sorted(predicates.items(), key=lambda item: len(item[1][0]))}
    for pred in predicates:
        to_print_line = [get_readable_list(fa, world) for fa in predicates[pred]]
        print('  ', pred, to_print_line)
    print('----------------')


def get_pddl_from_list(fact, world):
    fact = get_readable_list(fact, world, NAME_ONLY=True)
    line = ' '.join([str(ele) for ele in fact])
    line = line.replace("'", "")
    return '(' + line + ')'


def generate_problem_pddl(state, pddlstream_problem,
                          world_name='lisdf', domain_name='domain', out_path=None):
    from pybullet_tools.logging import myprint as print
    facts = pddlstream_problem.init
    goals = pddlstream_problem.goal
    if goals[0] == 'and':
        goals = [list(n) for n in goals[1:]]
    world = state.world

    PDDL_STR = """
(define
  (problem {world_name})
  (:domain {domain_name})

  (:objects
    {objects_pddl}
  )

  (:init
{init_pddl}
  )

  (:goal (and
    {goal_pddl}
  ))
)
        """

    kinds = {}  # pred: continuous vars
    by_len = {}  # pred: length of fact
    predicates = {}  # pred: [fact]
    all_pred_names = {}  # pred: arity
    for fact in facts:
        pred = fact[0]
        if pred in ['=', 'wconf', 'inwconf']: continue
        if pred.lower() not in all_pred_names:
            all_pred_names[pred.lower()] = len(fact[1:])
        fact = get_pddl_from_list(fact, world)

        if pred not in predicates:
            predicates[pred] = []

            num_con = len([o for o in fact[1:] if not isinstance(o, str)])
            if num_con not in kinds:
                kinds[num_con] = []
            kinds[num_con].append(pred)

            num = len(fact)
            if num not in by_len:
                by_len[num] = []
            by_len[num].append(pred)

        predicates[pred].append(fact)
    kinds = {k: v for k, v in sorted(kinds.items(), key=lambda item: item[0])}
    by_len = {k: v for k, v in sorted(by_len.items(), key=lambda item: item[0])}

    init_pddl = ''
    for kind, preds in kinds.items():
        pp = {k: v for k, v in predicates.items() if k in preds}

        if kind == 0:
            init_pddl += '\t;; discrete facts (e.g. types, affordances)'
        else:
            init_pddl += '\t;; facts involving continuous vars'

        for oo, ppds in by_len.items():
            ppp = {k: v for k, v in pp.items() if k in ppds}
            ppp = {k: v for k, v in sorted(ppp.items())}
            for pred in ppp:
                init_pddl += '\n\t' + '\n\t'.join(predicates[pred])
            init_pddl += '\n'

    objects = [o.name for o in world.BODY_TO_OBJECT.values()]
    objects.extend(['left', 'right'])
    objects_pddl = '\n\t'.join(sorted(objects))
    goal_pddl = '\n\t'.join([get_pddl_from_list(g, world) for g in sorted(goals)])
    problem_pddl = PDDL_STR.format(
        objects_pddl=objects_pddl, init_pddl=init_pddl, goal_pddl=goal_pddl,
        world_name=world_name, domain_name=domain_name
    )
    if out_path != None:
        with open(out_path, 'w') as f:
            f.writelines(problem_pddl)
    else:
        print(f'----------------{problem_pddl}')
    return all_pred_names


def print_plan(plan, world=None):
    from pddlstream.language.constants import Equal, AND, PDDLProblem, is_plan
    from pybullet_tools.logging import myprint as print

    if not is_plan(plan):
        return
    step = 1
    print('Plan:')
    for action in plan:
        name, args = action
        args2 = [str(a) for a in get_readable_list(args, world)]
        print('{:2}) {} {}'.format(step, name, ' '.join(args2)))
        step += 1
    print()


def print_goal(goal, world=None):
    from pybullet_tools.logging import myprint as print

    print(f'Goal ({len(goal) - 1}): ({goal[0]}')
    for each in get_readable_list(goal[1:], world):
        print(f'   {each},')
    print(')')


#######################################################

def is_placement(body, surface, link=None, **kwargs):
    if isinstance(surface, tuple):
        surface, _, link = surface
    return is_placed_on_aabb(body, get_aabb(surface, link), **kwargs)


def is_contained(body, space):
    if isinstance(space, tuple):
        return aabb_contains_aabb(get_aabb(body), get_aabb(space[0], link=space[-1]))
    return aabb_contains_aabb(get_aabb(body), get_aabb(space))


#######################################################

def save_pickle(pddlstream_problem, plan, preimage):
    ## ------------------- save the plan for debugging ----------------------
    # doesn't work because the reconstructed plan and preimage by pickle have different variable index
    import pickle
    import os
    from os.path import join, dirname, abspath
    ROOT_DIR = abspath(join(dirname(__file__), os.pardir))
    file = join(ROOT_DIR, '..', 'leap', 'pddlstream_plan.pkl')
    if isfile(file): os.remove(file)
    with open(file, 'wb') as outp:
        pickle.dump(pddlstream_problem.init, outp, pickle.HIGHEST_PROTOCOL)
        pickle.dump(plan, outp, pickle.HIGHEST_PROTOCOL)
        pickle.dump(preimage, outp, pickle.HIGHEST_PROTOCOL)
    # ------------------- save the plan for debugging ----------------------


def pose_to_xyzyaw(pose):
    xyzyaw = list(nice_tuple(pose[0]))
    xyzyaw.append(nice_float(euler_from_quat(pose[1])[2]))
    return tuple(xyzyaw)


def xyzyaw_to_pose(xyzyaw):
    return tuple((xyzyaw[:3], quat_from_euler(Euler(0, 0, xyzyaw[-1]))))


def draw_collision_shapes(body, links=[]):
    """ not working """
    if isinstance(body, tuple):
        body, link = body
        links.append(link)
    if len(links) == 0:
        links = get_links(body)
    body_from_world = get_pose(body)
    for link in links:
        collision_data = set(get_collision_data(body, link))
        for i in range(len(collision_data)):
            shape = collision_data[i]
            shape_from_body = (shape.local_frame_pos, shape.local_frame_orn)
            shape_from_world = multiply(shape_from_body, body_from_world)
            w, l, h = shape.dimensions
            tmp = create_box(w, l, h)
            set_pose(tmp, shape_from_world)
            print(
                f'link = {link}, colldion_body = {i} | dims = {nice(shape.dimensions)} | shape_from_world = {nice(shape_from_world)}')



def visualize_point(point, world):
    z = 0
    if len(point) == 3:
        x, y, z = point
    else:
        x, y = point
    body = create_box(.05, .05, .05, mass=1, color=(1, 0, 0, 1))
    set_pose(Pose(point=Point(x, y, z)))


#######################################################

def nice_float(ele):
    if isinstance(ele, int) or ele.is_integer():
        return int(ele)
    else:
        return round(ele, 3)

def nice_tuple(tup):
    new_tup = []
    for ele in tup:
        new_tup.append(nice_float(ele))
    return tuple(new_tup)

def nice(tuple_of_tuples):

    ## float, int
    if isinstance(tuple_of_tuples, float):
        return nice_float(tuple_of_tuples)

    ## position, pose
    elif isinstance(tuple_of_tuples[0], tuple):

        ## pose = point + euler -> (x, y, z, yaw)
        if len(tuple_of_tuples[0]) == 3 and len(tuple_of_tuples[1]) == 4:
            xyzyaw = list(nice_tuple(tuple_of_tuples[0]))
            xyzyaw.append(nice_float(euler_from_quat(tuple_of_tuples[1])[2]))
            return tuple(xyzyaw)

        new_tuple = []
        for tup in tuple_of_tuples:
            new_tuple.append(nice_tuple(tup))

        return tuple(new_tuple)

    ## point, euler, conf
    return nice_tuple(tuple_of_tuples)

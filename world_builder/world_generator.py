import os
import sys
import json
import copy
import shutil
from os.path import join, isdir, isfile, dirname, abspath
from os import listdir

from pybullet_tools.utils import get_bodies, euler_from_quat, get_collision_data, get_joint_name, \
    get_joint_position, get_camera, joint_from_name, get_color, disconnect, reset_simulation
from pybullet_tools.pr2_utils import get_arm_joints, get_group_joints, PR2_GROUPS
from pybullet_tools.bullet_utils import get_readable_list, LINK_STR, get_scale_by_category, nice
from .entities import Robot, LINK_STR
from .utils import read_xml, get_file_by_category, get_model_scale

from lisdf_tools.lisdf_loader import get_depth_images

LISDF_PATH = join('assets', 'scenes')
EXP_PATH = join('test_cases')

# ACTOR_STR = """
#     <include name="pr2">
#       <uri>../models/drake/pr2_description/urdf/pr2_simplified.urdf</uri>
#       {pose_xml}
#     </include>
# """
MODEL_BOX_STR = """
    <model name="{name}">
      <static>{is_static}</static>
      {pose_xml}
      <link name="box">
        <collision name="box_collision">
          <geometry>
            <box>
              <size>{wlh}</size>
            </box>
          </geometry>
        </collision>
        <visual name="box_visual">
          <geometry>
            <box>
              <size>{wlh}</size>
            </box>
          </geometry>
          <material>
            <diffuse>{rgb} 1</diffuse>
          </material> 
        </visual>
      </link>
    </model>
"""
MODEL_URDF_STR = """
    <include name="{name}">
      <uri>{file}</uri>
      <static>{is_static}</static>
      <scale>{scale}</scale>
      {pose_xml}
    </include>
"""
MODEL_STATE_STR = """
      <model name="{name}">{joints_xml}
      </model>"""
STATE_JOINTS_STR = """
        <joint name="{name}"><angle>{angle}</angle></joint>"""
STATE_STR = """
    <state world_name="{name}">{state_sdf}
    </state>
"""
WORLD_STR = """<?xml version="1.0" ?>
<!-- sdf file created by Yang's kitchen scene generator -->
<sdf version="1.9">
  <world name="{name}">
{camera_sdf}
{actor_sdf}
{models_sdf}
{state_sdf}
  </world>
</sdf>"""
CAMERA_STR = """
    <gui>
      <camera name="default_camera" definition_type="lookat">
        <xyz>{camera_point}</xyz>
        <point_to>{target_point}</point_to>
      </camera>
    </gui>
"""

def list_to_xml(lst):
    return " ".join([str(round(o, 3)) for o in lst])

def to_pose_xml(pose):
    xyz, quat = pose
    euler = euler_from_quat(quat)
    return f"<pose>{list_to_xml(xyz)} {list_to_xml(euler)}</pose>"


def get_camera_spec():
    import math
    _, _, _, _, _, _, _, _, yaw, pitch, dist, target = get_camera()
    pitch_rad = math.radians(pitch)
    dz = -dist * math.sin(pitch_rad)
    l = abs(dist * math.cos(pitch_rad))
    yaw_rad = math.radians(yaw)
    dx = l * math.sin(yaw_rad)
    dy = -l * math.cos(yaw_rad)
    camera = [target[0]+dx, target[1]+dy, target[2]+dz]
    return camera, list(target)


def to_lisdf(world, init, floorplan=None, exp_name=None, world_name=None,
             root_path=None, out_path=None, verbose=True):
    """ if exp_name != None, will be generated into kitchen-world/experiments/{exp_name}/scene.lisdf
        if world_name != None, will be generated into kitchen-world/assets/scenes/{world_name}.lisdf
        if out_path != None, will be generated into out_path
    """

    exp_path = EXP_PATH
    lisdf_path = LISDF_PATH
    if root_path != None:
        exp_path = join(root_path, exp_path)
        lisdf_path = join(root_path, lisdf_path)

    if floorplan != None:
        objects, _, _, SCALING, _, _, _, _ = read_xml(floorplan)
        objects = {k.lower(): v for k, v in objects.items()}
    else:
        objects = []
        SCALING = 1

    if exp_name != None:
        outpath = join(exp_path, exp_name)
        if isdir(outpath):
            shutil.rmtree(outpath)
        os.mkdir(outpath)
        outpath = join(exp_path, exp_name, "scene.lisdf")
        world_name = exp_name
    elif out_path != None:
        outpath = out_path
    else:
        outpath = join(lisdf_path, f"{world_name}.lisdf")

    _, _, _, _, _, _, _, _, yaw, pitch, dist, target = get_camera()

    def get_file_scale(name):
        o = objects[name]
        file = get_file_by_category(o['category'])
        l = o['l'] / SCALING
        w = o['w'] / SCALING
        scale = get_model_scale(file, l, w)
        return file, scale

    actor_sdf = ''
    models_sdf = ''
    state_sdf = ''
    model_joints = {}  ## model_name : joints_xml
    c = world.cat_to_bodies
    movables = c('moveable')
    joints = c('door') + c('drawer') + c('knob')  ## [f[1] for f in init if f[0] == 'joint']

    ## first add all actor and models
    bodies = copy.deepcopy(get_bodies())
    bodies.sort()
    for body in bodies:
        if body in world.BODY_TO_OBJECT:
            obj = world.BODY_TO_OBJECT[body]
        elif body in world.ROBOT_TO_OBJECT:
            obj = world.ROBOT_TO_OBJECT[body]
        else:
            continue

        is_static = 'false' if body in movables else 'true'
        pose_xml = to_pose_xml(obj.get_pose())
        # print(obj.name)
        if isinstance(obj, Robot):
            ACTOR_STR = world.robot.get_lisdf_string()
            actor_sdf = ACTOR_STR.format(name=obj.name, pose_xml=pose_xml)
            if exp_name != None:
                actor_sdf = actor_sdf.replace('../models/', '../../assets/models/')
            if out_path != None:
                actor_sdf = actor_sdf.replace('../models/', '../../models/')

            ## robot joint states
            joints_xml = ''
            all_joints = world.robot.get_all_joints()
            js = [joint_from_name(body, j) for j in all_joints]
            # js = list(get_group_joints(body, 'torso'))
            # js.extend(list(get_arm_joints(body, 'left'))+list(get_arm_joints(body, 'right')))
            for j in js:
                joints_xml += STATE_JOINTS_STR.format(
                    name=get_joint_name(body, j),
                    angle=round(get_joint_position(body, j), 3)
                )
            state_sdf += MODEL_STATE_STR.format(name=obj.name, joints_xml=joints_xml)

        elif obj.is_box: ## and obj.name not in objects:
            if len(get_collision_data(body)) == 0:
                print('world_generator | len(get_collision_data(body)) == 0')
            dim = get_collision_data(body)[0].dimensions
            wlh = " ".join([str(round(o, 3)) for o in dim])
            color = get_color(obj)[:3]
            rgb = " ".join([str(round(o, 3)) for o in color])
            models_sdf += MODEL_BOX_STR.format(
                name=obj.name, is_static=is_static,
                pose_xml=pose_xml, wlh=wlh, rgb=rgb
            )

        else:
            if not hasattr(obj, 'path'):
                print('world_generator.file', obj)
            file = obj.path
            scale = get_scale_by_category(file, obj.category)
            # if obj.category in OBJ_SCALES:
            #     scale = OBJ_SCALES[obj.category]
            #     file = get_file_by_category(obj.category)
            # else:
            #     file, scale = get_file_scale(obj.name)
            if exp_name != None:
                file = file.replace('../assets/', '../../assets/')
            if out_path != None:
                file = file.replace('../assets/', '../../')

            models_sdf += MODEL_URDF_STR.format(
                name=obj.lisdf_name, file=file,
                is_static=is_static,
                pose_xml=pose_xml, scale=scale
            )

    ## then add joint states of models
    for j in joints:
        body, joint = j
        name = world.BODY_TO_OBJECT[body].name
        joint_name = world.BODY_TO_OBJECT[j].name
        if name not in model_joints:
            model_joints[name] = ""
        model_joints[name] += STATE_JOINTS_STR.format(
            name=joint_name.replace(name+LINK_STR, ''),
            angle=round(get_joint_position(body, joint), 3)
        )
    for name, joints_xml in model_joints.items():
        state_sdf += MODEL_STATE_STR.format(name=name, joints_xml=joints_xml)
    state_sdf = STATE_STR.format(
        name=world_name, state_sdf=state_sdf
    )

    ## finally add camera pose
    cp, tp = get_camera_spec()
    camera_sdf = CAMERA_STR.format(camera_point=list_to_xml(cp), target_point=list_to_xml(tp))

    ## put everything together
    world_sdf = WORLD_STR.format(
        name=world_name, actor_sdf=actor_sdf, models_sdf=models_sdf,
        state_sdf=state_sdf, camera_sdf=camera_sdf
    )

    with open(outpath, 'w') as f:
        f.write(world_sdf)
    if verbose: print(f'\n\nwritten {outpath}\n\n')

    return LISDF_PATH


def test_get_camera_spec():
    from pybullet_tools.utils import connect, disconnect, set_camera_pose, get_camera, \
        create_box, set_pose, quat_from_euler, set_renderer, wait_if_gui, unit_pose
    import numpy as np
    import random

    def random_point(lim=9):
        return [random.uniform(-lim, lim) for k in range(3)]

    def equal(a, b, epsilon=0.01):
        return np.linalg.norm(np.asarray(a) - np.asarray(b)) < epsilon

    connect(use_gui=True, shadows=False, width=1980, height=1238)

    set_renderer(True)
    something = create_box(1, 1, 1, mass=1)
    somepose = unit_pose() ## (random_point(3), quat_from_euler((0, 0, 0)))
    set_pose(something, somepose)
    # set_static()

    for i in range(10):
        camera_point = random_point() ## [3, 5, 3] ##
        target_point = random_point() ## [0, 6, 1] ##
        print(f'test {i} | \t camera_point {nice(camera_point)}\t target_point {nice(target_point)}')

        ## somehow it can't set the pose ....
        set_camera_pose(camera_point=camera_point, target_point=target_point)
        camera_point_est, target_point_est = get_camera_spec()
        if not (equal(camera_point, camera_point_est) and equal(target_point, target_point_est)):
            print(f'test {i} | \t camera_point_est {nice(camera_point_est)}\t target_point_est {nice(target_point_est)}')
    disconnect()

def clean_domain_pddl(pddl_str, all_pred_names):
    string = 'xyzijk'
    need_preds = list(all_pred_names)
    pddl_str = pddl_str[:pddl_str.index('(:functions')].lower()
    pddl_str = pddl_str[:pddl_str.rfind(')')]
    started = False
    for line in pddl_str.split('\n'):
        if started and '(' in line and ')' in line:
            line = line[line.index('(')+1:line.index(')')]
            if ' ' in line:
                line = line[:line.index(' ')]
            if line in all_pred_names and line in need_preds:
                need_preds.remove(line)
        if '(:predicates' in line:
            started = True
    pddl_str = pddl_str + '\n'
    for n in need_preds:
        args = f'{n}'
        for i in range(all_pred_names[n]):
            args += f" ?{string[i]}"
        pddl_str += f'    ({args})\n'
    pddl_str += '  )\n)'
    # print(pddl_str)
    return pddl_str


def save_to_exp_folder(state, init, goal, out_path):
    if isinstance(goal, tuple): return  ## debug problems instead of real problems

    floorplan = state.world.floorplan
    world_name = 'experiment'
    out_path = out_path.replace('.mp4', '')

    to_lisdf(state.world, init, floorplan=floorplan, world_name=world_name,
             out_path=out_path+'_scene.lisdf')
    generate_problem_pddl(state, init, goal, world_name=world_name,
                          out_path=out_path+'_problem.pddl')


def save_to_outputs_folder(outpath, exp_path, data_generation=False):
    exp_path = exp_path.replace('.mp4', '')

    if data_generation:
        original = 'visualizations'
        if isfile(join(original, 'log.json')):
            for subdir in ['constraint_networks', 'stream_plans']:
                if len(listdir(join(original, subdir))) < 1: continue
                shutil.move(join(original, subdir), join(outpath, subdir))
            for subfile in ['log.json']:
                shutil.move(join(original, subfile), join(outpath, subfile))
        else:
            new_outpath = f"{outpath}_failed"
            shutil.move(outpath, new_outpath)
            outpath = new_outpath

    """ =========== move to data collection folder =========== """
    ## 'one_fridge_pick_pr2'
    data_path = outpath.replace('test_cases', join('outputs', 'one_fridge_pick_pr2'))
    shutil.move(outpath, data_path)

    """ =========== move the log and plan =========== """
    shutil.move(f"{exp_path}_log.txt", join(data_path, 'log.txt'))
    shutil.move(f"{exp_path}_time.json", join(data_path, 'plan.json'))
    shutil.move(f"{exp_path}_commands.pkl", join(data_path, 'commands.pkl'))


def save_to_kitchen_worlds(state, pddlstream_problem, exp_name='test_cases', EXIT=True,
                           floorplan=None, world_name=None, root_path=None, DEPTH_IMAGES=False):
    exp_path = EXP_PATH
    if root_path != None:
        exp_path = join(root_path, exp_path)
    outpath = join(exp_path, exp_name)
    if isdir(outpath):
        shutil.rmtree(outpath)
    os.mkdir(outpath)

    ## --- scene in scene.lisdf
    to_lisdf(state.world, pddlstream_problem.init, floorplan=floorplan, exp_name=exp_name,
             world_name=world_name, root_path=root_path)
    state.world.outpath = outpath

    ## --- init and goal in problem.pddl
    all_pred_names = generate_problem_pddl(state, pddlstream_problem.init, pddlstream_problem.goal,
                             world_name=world_name, out_path=join(outpath, 'problem.pddl'))

    import platform
    robot = state.world.robot
    # body_to_name = {i: state.world.body_to_name(i) for i in get_bodies()}
    body_to_name = {str(k): v.name for k, v in state.world.BODY_TO_OBJECT.items()}
    body_to_name[str(robot.body)] = robot.name
    body_to_name = dict(sorted(body_to_name.items(), key=lambda item: item[0]))
    config = {
        'base_limits': state.world.robot.custom_limits,  ## state.world.args.base_limits,
        'body_to_name': body_to_name,
        'system': platform.system()
    }
    if state.world.camera != None:
        config['obs_camera_pose'] = state.world.camera.pose

    ## --- domain and stream copied over  ## shutil.copy()
    with open(join(outpath, 'domain_full.pddl'), 'w') as f:
        f.write(pddlstream_problem.domain_pddl)
    with open(join(outpath, 'domain.pddl'), 'w') as f:
        f.write(clean_domain_pddl(pddlstream_problem.domain_pddl, all_pred_names))
    with open(join(outpath, 'stream.pddl'), 'w') as f:
        f.write(pddlstream_problem.stream_pddl)
    with open(join(outpath, 'planning_config.json'), 'w') as f:
        json.dump(config, f)

    if DEPTH_IMAGES and state.world.camera != None:
        # reset_simulation()
        # get_depth_images(outpath, camera_pose=state.world.camera.pose,
        #                  img_dir=join(outpath, 'depth_maps'))
        reset_simulation()
        get_depth_images(outpath, camera_pose=state.world.camera.pose,
                         img_dir=join(outpath, 'rgb_images'), rgb=True)
        # reset_simulation()
        # get_depth_images(outpath, camera_pose=state.world.camera.pose,
        #                  rgbd=True, robot=False, img_dir=outpath)

    if EXIT: sys.exit()


def save_to_test_cases(state, goal, template_name, floorplan, out_dir, root_path='..',
                       verbose=True, DEPTH_IMAGES=False):

    exp_path = EXP_PATH
    if root_path is not None:
        exp_path = join(root_path, exp_path)

    outpath = join(exp_path, out_dir)
    if not isdir(outpath):
        os.mkdir(outpath)

    ## get current index
    index = len([f for f in listdir(outpath) if 'DS_Store' not in f]) + 1
    outpath = join(outpath, str(index))
    os.mkdir(outpath)

    init = state.get_facts(verbose=verbose)

    ## --- scene in scene.lisdf
    to_lisdf(state.world, init, floorplan=floorplan, exp_name=join(out_dir, str(index)),
             world_name=template_name, root_path=root_path, verbose=verbose)

    ## --- init and goal in problem.pddl
    generate_problem_pddl(state, init, goal, world_name=template_name,
                          out_path=join(outpath, 'problem.pddl'))

    ## --- planning related files and params are referred to in template directory
    config = {
        'base_limits': state.world.robot.custom_limits,
        'domain_full': join(template_name, 'domain_full.pddl'),
        'domain': join(template_name, 'domain.pddl'),
        'stream': join(template_name, 'stream.pddl'),
    }
    with open(join(outpath, 'planning_config.json'), 'w') as f:
        json.dump(config, f, indent=4)

    """ save depth image """
    if DEPTH_IMAGES:
        reset_simulation()
        get_depth_images(outpath, camera_pose=state.world.camera.pose,
                         img_dir=join(outpath, 'depth_maps'), verbose=True)
    else:
        state.world.visualize_image(img_dir=outpath)


def get_pddl_from_list(fact, world):
    fact = get_readable_list(fact, world, NAME_ONLY=True, TO_LISDF=True)
    line = ' '.join([str(ele) for ele in fact])
    line = line.replace("'", "")
    return '(' + line + ')'


def generate_problem_pddl(state, facts, goals, ## pddlstream_problem,
                          world_name='lisdf', domain_name='domain', out_path=None):
    from pybullet_tools.logging import myprint as print
    # facts = pddlstream_problem.init
    # goals = pddlstream_problem.goal
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
    for fact in list(set(facts)):
        pred = fact[0]
        if pred in ['=']: continue
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

    objects = [o.lisdf_name for o in world.BODY_TO_OBJECT.values()]
    objects.extend(world.robot.joint_groups)
    objects.extend([str(i[1]) for i in facts if i[0].lower() == 'wconf'])
    objects_pddl = '\n\t'.join(sorted(objects))

    goal_pddl = '\n\t'.join([get_pddl_from_list(g, world) for g in sorted(goals)]).lower()

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
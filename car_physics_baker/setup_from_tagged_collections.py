"""Register tagged vehicle collections for Car Physics Baker.

Expected collection custom property: rev_car = vehicle name.
Expected object custom properties: rev_car = vehicle name and
rev_role = BODY, FL, FR, RL, or RR.

Run this script in Blender's Text Editor after enabling Car Physics Baker.
It deliberately creates a temporary straight test path for each vehicle;
replace these paths with the real course before baking a production run.
"""

import bpy
from mathutils import Vector


ROLES = ("BODY", "FL", "FR", "RL", "RR")
PATH_PREFIX = "CPB_配置確認コース_"
PATH_MARKER = "cpb_generated_test_path"


def _tagged_vehicle_collections(scene):
    result = []
    for collection in scene.collection.children_recursive:
        vehicle_name = collection.get("rev_car")
        if not vehicle_name:
            continue
        by_role = {role: [] for role in ROLES}
        for obj in collection.all_objects:
            role = obj.get("rev_role")
            if role in by_role:
                by_role[role].append(obj)
        if any(by_role.values()):
            duplicates = [role for role, objects in by_role.items() if len(objects) > 1]
            missing = [role for role, objects in by_role.items() if not objects]
            if duplicates or missing:
                detail = []
                if duplicates:
                    detail.append("重複=" + ", ".join(duplicates))
                if missing:
                    detail.append("不足=" + ", ".join(missing))
                raise RuntimeError(collection.name + ": 車両タグが不完全です（" + "; ".join(detail) + "）。")
            result.append((collection, {role: objects[0] for role, objects in by_role.items()}))
    return result


def _validate_targets(groups):
    axes = {"POS_Y": Vector((0, 1, 0)), "NEG_Y": Vector((0, -1, 0)),
            "POS_X": Vector((1, 0, 0)), "NEG_X": Vector((-1, 0, 0))}
    directions = []
    for collection, objects in groups:
        if len({obj.as_pointer() for obj in objects.values()}) != len(ROLES):
            raise RuntimeError(collection.name + ": BODYと4輪には別々のオブジェクトを指定してください。")
        for role, obj in objects.items():
            if obj.parent or obj.constraints:
                raise RuntimeError(obj.name + ": 親または制約があります。CPB用ターゲットから除去してください。")
            animation = obj.animation_data
            if animation and ((animation.action and len(animation.action.fcurves)) or animation.nla_tracks or animation.drivers):
                raise RuntimeError(obj.name + ": 既存アニメーションがあります。ベイクを消してから再登録してください。")
            if max(abs(value - 1.0) for value in obj.matrix_world.to_scale()) > 1e-5:
                raise RuntimeError(obj.name + ": ワールドスケールが1ではありません。適用してから再登録してください。")

        front = (objects["FL"].matrix_world.translation + objects["FR"].matrix_world.translation) * 0.5
        rear = (objects["RL"].matrix_world.translation + objects["RR"].matrix_world.translation) * 0.5
        forward = front - rear
        if forward.length < 1e-5:
            raise RuntimeError(collection.name + ": 前後輪の位置から前方向を判定できません。")
        forward.normalize()
        axis = max(axes, key=lambda key: forward.dot(axes[key]))
        if forward.dot(axes[axis]) < 0.999:
            raise RuntimeError(collection.name + ": 車の前方向をXまたはY軸にそろえてください。")
        directions.append(axis)

    if len(set(directions)) != 1:
        raise RuntimeError("全車両の前方向を同じ軸にそろえてください。")
    return directions[0]


def _remove_previous_test_paths(scene):
    for obj in list(scene.objects):
        if obj.get(PATH_MARKER):
            curve = obj.data if obj.type == "CURVE" else None
            bpy.data.objects.remove(obj, do_unlink=True)
            if curve and curve.users == 0:
                bpy.data.curves.remove(curve)


def _make_test_path(scene, collection, objects, axis):
    curve = bpy.data.curves.new(PATH_PREFIX + collection.name, "CURVE")
    curve.dimensions = "3D"
    spline = curve.splines.new("POLY")
    spline.points.add(2)
    forward = {"POS_Y": Vector((0, 1, 0)), "NEG_Y": Vector((0, -1, 0)),
               "POS_X": Vector((1, 0, 0)), "NEG_X": Vector((-1, 0, 0))}[axis]
    origin = objects["BODY"].matrix_world.translation.copy()
    origin.z = sum(objects[role].matrix_world.translation.z - max(objects[role].dimensions) / 2
                   for role in ("FL", "FR", "RL", "RR")) / 4
    for point, distance in zip(spline.points, (0, 30, 80)):
        point.co = (*(origin + forward * distance), 1)
    path = bpy.data.objects.new(PATH_PREFIX + collection.name, curve)
    scene.collection.objects.link(path)
    path.hide_render = True
    path[PATH_MARKER] = True
    return path


def setup():
    scene = bpy.context.scene
    if not hasattr(scene, "cpb"):
        raise RuntimeError("Car Physics Bakerアドオンを有効化してから実行してください。")

    groups = _tagged_vehicle_collections(scene)
    if not groups:
        raise RuntimeError("rev_car / rev_roleタグ付きの車両コレクションが見つかりません。")
    groups.sort(key=lambda group: (group[0].get("rev_car") != "R32", group[0].name))
    forward_axis = _validate_targets(groups)

    # Clear scene-level CPB state so stale world-space cpb_rest caches cannot
    # pull vehicles back to a previous placement when the next bake begins.
    scene.property_unset("cpb")
    settings = scene.cpb
    settings.cars.clear()
    settings.use_armature = False
    settings.model_scale = 1
    settings.wheel_radius = 0
    settings.forward_axis = forward_axis
    settings.drive_mode = "PATH"
    settings.use_multi = len(groups) > 1
    settings.preset = "SPORTS"
    settings.top_speed = 35
    settings.road_noise = 0
    settings.show_trajectory = False
    settings.use_scene_range = True
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1

    _remove_previous_test_paths(scene)
    for index, (collection, objects) in enumerate(groups):
        item = settings if index == 0 else settings.cars.add()
        if index:
            item.name = collection.get("rev_car")
            item.overtake = False
            item.avoid = False
        item.body = objects["BODY"]
        for role in ("FL", "FR", "RL", "RR"):
            setattr(item, "wheel_" + role.lower(), objects[role])
        for obj in objects.values():
            for key in list(obj.keys()):
                if key.startswith("cpb_"):
                    del obj[key]
        item.path = _make_test_path(scene, collection, objects, forward_axis)

    bpy.context.view_layer.update()
    print("Car Physics: 登録完了", len(groups), "台。前方", forward_axis,
          "縮尺1 / 半径自動。生成パスは確認用です。実コースと地面を設定後に本番ベイクしてください。")
    return groups


if __name__ == "__main__":
    setup()

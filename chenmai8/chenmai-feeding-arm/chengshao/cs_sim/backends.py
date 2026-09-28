"""运动学后端：三种模型装载途径的统一抽象（开发指令 §5.1 回退链）。

- ``MujocoBackend``      —— 直接加载 MJCF（tier 1 ``mjcf``）或 URDF
                            （tier 2 ``urdf_mujoco``），物理引擎原生路径；
- ``IkpyChainBackend``   —— ikpy 链：可直接由 URDF 文件构建（报告层记为
                            ``chain_urdf_ikpy``），或使用 ``BUILTIN_CHAIN``
                            名义几何常数自建（tier 3 ``chain_builtin``，
                            无文件依赖的最后手段）。

统一约定（冻结）：
- 关节向量 q 的长度 = 模型可动关节数（参考模型为 6 = 5 个臂关节 + 1 个
  末端夹爪关节；夹爪不影响工具点位姿。cs_schema N_ARM_JOINTS=7 的统一
  数组与本模型的映射由执行层负责）；
- 末端（TCP）定义为参考模型的 ``gripperframe`` 工具系：零位时位于
  (0.3914, 0.0000, 0.2265) m。URDF 途径的工具系约定与参考 TCP 相差一个
  固定旋转（``URDF_TOOL_ALIGN_QUAT``，绕工具系 Y 轴 +90°；来源：同一
  固定关节在两套模型里的写法差异。实测两模型 TCP 位置逐点一致
  <=4e-6 m）。后端内部完成对齐，各 tier 对外输出同一定义的 TCP。
"""

from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from pathlib import Path

import numpy as np

from .frames import matrix_from_quat, matrix_from_rpy, quat_from_matrix, rpy_from_matrix
from .model_source import MODEL_TIER_CHAIN_BUILTIN, MODEL_TIER_MJCF, MODEL_TIER_URDF

__all__ = [
    "KinematicBackend",
    "MujocoBackend",
    "IkpyChainBackend",
    "URDF_TOOL_ALIGN_QUAT",
    "BUILTIN_CHAIN",
]

# 参考 TCP（MJCF 工具系 site）与 URDF 固定工具关节写法之间的固定约定差：
# 同一物理工具系，URDF 写法为 Ry(180°)、MJCF site 写法为 Ry(90°)（连杆系两
# 侧一致），故 URDF 途径需在工具姿态上后乘 Ry(-90°) 使 TCP 定义一致。
URDF_TOOL_ALIGN_QUAT: tuple[float, float, float, float] = (
    0.7071067811865476, 0.0, -0.7071067811865476, 0.0,  # 绕 Y 轴 -90°
)


def _sha16(path: Path) -> str:
    """文件内容 SHA-256 前 16 位十六进制（报告用无泄漏版本指纹）。"""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _relative_to_cwd_if_possible(path: Path) -> Path:
    """尽量把路径转为相对 cwd 的形式（规避物理引擎对非 ASCII 绝对路径的缺陷）。"""
    import os

    try:
        return Path(os.path.relpath(path, Path.cwd()))
    except ValueError:  # 跨盘符无法相对化
        return path


class KinematicBackend(ABC):
    """统一运动学后端接口（本包内部抽象；ArmModel 面向契约暴露）。"""

    tier: str

    @property
    @abstractmethod
    def n_joints(self) -> int: ...

    @property
    @abstractmethod
    def joint_names(self) -> list[str]: ...

    @property
    @abstractmethod
    def joint_lower(self) -> np.ndarray: ...

    @property
    @abstractmethod
    def joint_upper(self) -> np.ndarray: ...

    @abstractmethod
    def fk(self, q: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """返回 (TCP 位置 (3,), TCP 旋转矩阵 (3,3))。"""

    @abstractmethod
    def jacobian(self, q: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """返回 (位置雅可比 (3,n), 角速度雅可比 (3,n))，world 系，列对齐 q。"""

    @abstractmethod
    def source_meta(self) -> dict:
        """中性元数据（tier/指纹/说明），供报告记录，不含本地敏感路径。"""


# ---------------------------------------------------------------------------
# tier 1 / tier 2：物理引擎直接加载
# ---------------------------------------------------------------------------


class MujocoBackend(KinematicBackend):
    """物理引擎原生加载 MJCF（xml/mjcf）或 URDF。

    MJCF 途径：TCP 取名为 ``gripperframe`` 的 site（参考定义）。
    URDF 途径：物理引擎导入会合并无质量的固定体，工具系 link 不保留，
    故 TCP = 末端连杆体系 ×（URDF 固定工具关节变换）×（约定对齐旋转）。
    固定工具关节的 xyz/rpy 从 URDF 原文解析，缺失时退化为单位变换。
    """

    _EE_SITE_CANDIDATES = ("gripperframe", "gripper_frame", "tool0", "ee")
    _EE_BODY_CANDIDATES = ("gripper_link", "gripper", "tool0", "ee_link", "ee")

    def __init__(self, path: str | Path) -> None:
        import mujoco  # 延迟导入：tier 3 无需物理引擎

        self._path = Path(path)
        # Windows + 非 ASCII 安装路径：物理引擎按绝对路径打开会失败，
        # 相对路径可用（实测）——尽量改用相对 cwd 的加载路径。
        self._load_path = _relative_to_cwd_if_possible(self._path)
        suffix = self._path.suffix.lower()
        if suffix == ".urdf":
            self.tier = MODEL_TIER_URDF
        elif suffix in (".xml", ".mjcf"):
            self.tier = MODEL_TIER_MJCF
        else:
            raise ValueError(f"unsupported model file type: {suffix!r}")

        m = mujoco.MjModel.from_xml_path(str(self._load_path))
        self._model = m
        self._data = mujoco.MjData(m)

        # 关节表：仅 1 自由度铰链/滑移关节，按模型顺序；记录 (joint id, qposadr, dofadr)
        self._jids: list[int] = []
        self._qadr: list[int] = []
        self._dadr: list[int] = []
        names: list[str] = []
        for j in range(m.njnt):
            if int(m.jnt_type[j]) not in (
                int(mujoco.mjtJoint.mjJNT_HINGE),
                int(mujoco.mjtJoint.mjJNT_SLIDE),
            ):
                continue
            self._jids.append(j)
            self._qadr.append(int(m.jnt_qposadr[j]))
            self._dadr.append(int(m.jnt_dofadr[j]))
            names.append(mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_JOINT, j) or f"joint_{j}")
        if len(self._jids) < 2:
            raise ValueError(f"model has too few 1-dof joints: {len(self._jids)}")
        self._names = names
        self._lower = np.array(
            [m.jnt_range[j][0] if m.jnt_limited[j] else -np.pi for j in self._jids]
        )
        self._upper = np.array(
            [m.jnt_range[j][1] if m.jnt_limited[j] else np.pi for j in self._jids]
        )

        # TCP 解析
        self._ee_site = -1
        self._ee_body = -1
        self._tool_p = np.zeros(3)
        self._tool_R = np.eye(3)
        self._align_R = np.eye(3)
        if self.tier == MODEL_TIER_MJCF:
            for nm in self._EE_SITE_CANDIDATES:
                sid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_SITE, nm)
                if sid >= 0:
                    self._ee_site = sid
                    break
            if self._ee_site < 0:
                raise ValueError("no end-effector site found in MJCF model")
        else:
            for nm in self._EE_BODY_CANDIDATES:
                bid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, nm)
                if bid >= 0:
                    self._ee_body = bid
                    break
            if self._ee_body < 0:
                raise ValueError("no end-effector body found in URDF model")
            ee_name = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, self._ee_body) or "gripper"
            self._tool_p, self._tool_R = self._parse_urdf_tool_joint(self._path, ee_name)
            self._align_R = matrix_from_quat(np.array(URDF_TOOL_ALIGN_QUAT))

    @staticmethod
    def _parse_urdf_tool_joint(urdf_path: Path, ee_link: str) -> tuple[np.ndarray, np.ndarray]:
        """在 URDF 原文中找"末端连杆 -> *frame*"的固定关节，返回 (xyz, R_rpy)。"""
        root = ET.parse(str(urdf_path)).getroot()
        for joint in root.iter("joint"):
            if (joint.get("type") or "").lower() != "fixed":
                continue
            parent = joint.find("parent")
            child = joint.find("child")
            if parent is None or child is None:
                continue
            if parent.get("link") != ee_link:
                continue
            if "frame" not in (child.get("link") or "").lower():
                continue
            xyz = np.zeros(3)
            rpy = np.zeros(3)
            origin = joint.find("origin")
            if origin is not None:
                if origin.get("xyz"):
                    xyz = np.array([float(v) for v in origin.get("xyz").split()])
                if origin.get("rpy"):
                    rpy = np.array([float(v) for v in origin.get("rpy").split()])
            return xyz, matrix_from_rpy(*rpy)
        return np.zeros(3), np.eye(3)

    # -- KinematicBackend ------------------------------------------------------

    @property
    def n_joints(self) -> int:
        return len(self._jids)

    @property
    def joint_names(self) -> list[str]:
        return list(self._names)

    @property
    def joint_lower(self) -> np.ndarray:
        return self._lower.copy()

    @property
    def joint_upper(self) -> np.ndarray:
        return self._upper.copy()

    def _set_q(self, q: np.ndarray) -> None:
        if len(q) != self.n_joints:
            raise ValueError(f"q length {len(q)} != n_joints {self.n_joints}")
        for k, adr in enumerate(self._qadr):
            self._data.qpos[adr] = q[k]

    def fk(self, q: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        import mujoco

        self._set_q(q)
        mujoco.mj_kinematics(self._model, self._data)
        if self._ee_site >= 0:
            pos = self._data.site_xpos[self._ee_site].copy()
            rot = self._data.site_xmat[self._ee_site].reshape(3, 3).copy()
            return pos, rot
        Rb = self._data.xmat[self._ee_body].reshape(3, 3)
        pos = self._data.xpos[self._ee_body] + Rb @ self._tool_p
        rot = Rb @ self._tool_R @ self._align_R
        return np.asarray(pos).copy(), np.asarray(rot).copy()

    def jacobian(self, q: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        import mujoco

        self._set_q(q)
        mujoco.mj_kinematics(self._model, self._data)
        mujoco.mj_comPos(self._model, self._data)
        jacp = np.zeros((3, self._model.nv))
        jacr = np.zeros((3, self._model.nv))
        if self._ee_site >= 0:
            mujoco.mj_jacSite(self._model, self._data, jacp, jacr, self._ee_site)
        else:
            mujoco.mj_jacBody(self._model, self._data, jacp, jacr, self._ee_body)
        cols = np.asarray(self._dadr, dtype=int)
        return jacp[:, cols].copy(), jacr[:, cols].copy()

    def source_meta(self) -> dict:
        return {
            "tier": self.tier,
            "file_sha256_16": _sha16(self._path),
            "engine": "physics-engine native (mjcf)"
            if self.tier == MODEL_TIER_MJCF
            else "physics-engine native (urdf subset)",
            "note": "loaded and validated at load time",
        }


# ---------------------------------------------------------------------------
# tier 3：ikpy 名义链（内置常数，最后手段）
# ---------------------------------------------------------------------------

# 名义几何常数：从参考模型的 MJCF 逐字提取（各连杆 body 的 pos/quat 与工具系
# site 的 pos/quat）。本地无模型文件时以此复现同一运动学。四元数 [w, x, y, z]。
BUILTIN_CHAIN: dict = {
    "joints": [
        # (name, translation, quat_wxyz, (lower, upper))
        ("shoulder_pan", (0.0388353, 0.0, 0.0624), (0.0, 0.0, -1.0, 0.0),
         (-1.919862177193762, 1.919862177193762)),
        ("shoulder_lift", (-0.0303992, -0.0182778, -0.0542), (0.5, -0.5, -0.5, -0.5),
         (-1.7453292519943224, 1.7453292519943366)),
        ("elbow_flex", (-0.11257, -0.028, 0.0), (0.7071068, 0.0, 0.0, 0.7071068),
         (-1.69, 1.69)),
        ("wrist_flex", (-0.1349, 0.0052, 0.0), (0.7071068, 0.0, 0.0, -0.7071068),
         (-1.6580628494556928, 1.6580627293335335)),
        ("wrist_roll", (0.0, -0.0611, 0.0181), (0.0172091, -0.0172091, 0.7068973, 0.7068973),
         (-2.7438472969992493, 2.841206309382605)),
    ],
    "tool": {
        "translation": (-0.0079, -0.000218121, -0.0981274),
        "quat": (0.707107, 0.0, 0.707107, 0.0),
    },
}


class IkpyChainBackend(KinematicBackend):
    """ikpy 串联链后端：``urdf_path`` 给定时由 URDF 构建，否则用内置名义链。

    自带几何雅可比（由 forward_kinematics 的逐连杆位姿构造），不依赖 ikpy
    版本之间的雅可比 API 差异。
    """

    tier = MODEL_TIER_CHAIN_BUILTIN

    def __init__(self, urdf_path: str | Path | None = None) -> None:
        from ikpy.chain import Chain
        from ikpy.link import URDFLink

        self._urdf_path = Path(urdf_path) if urdf_path is not None else None
        if self._urdf_path is not None:
            self.tier = "chain_urdf_ikpy"
            base_elements = self._urdf_base_elements(self._urdf_path)
            import warnings

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")  # ikpy 对固定关节 axis 的无害告警
                self._chain = Chain.from_urdf_file(
                    str(self._urdf_path), base_elements=base_elements
                )
            self._links = list(self._chain.links)
            self._align_R = matrix_from_quat(np.array(URDF_TOOL_ALIGN_QUAT))
        else:
            links = []
            for name, trans, quat, bounds in BUILTIN_CHAIN["joints"]:
                links.append(
                    URDFLink(
                        name=name,
                        origin_translation=np.asarray(trans, dtype=float),
                        origin_orientation=rpy_from_matrix(matrix_from_quat(np.asarray(quat))),
                        rotation=np.array([0.0, 0.0, 1.0]),
                        bounds=tuple(bounds),
                    )
                )
            tool = BUILTIN_CHAIN["tool"]
            links.append(
                URDFLink(
                    name="tool_tcp",
                    origin_translation=np.asarray(tool["translation"], dtype=float),
                    origin_orientation=rpy_from_matrix(matrix_from_quat(np.asarray(tool["quat"]))),
                    rotation=None,
                    joint_type="fixed",
                )
            )
            self._chain = Chain(
                links=links,
                active_links_mask=[getattr(lk, "joint_type", "revolute") == "revolute" for lk in links],
                name="cs_builtin_arm",
            )
            self._links = links
            self._align_R = np.eye(3)  # 名义链常数即参考 TCP 约定，无需对齐

        # 活动关节 = revolute 链接（URDF 途径截断于工具系 link，夹爪指自然排除）
        self._active_idx = [
            i
            for i, lk in enumerate(self._links)
            if getattr(lk, "joint_type", "revolute") == "revolute"
        ]
        # 与 ikpy 链的活动掩码对齐（消除"fixed link 标为 active"的无害告警）
        mask = [i in set(self._active_idx) for i in range(len(self._links))]
        try:
            self._chain.active_links_mask = mask
        except Exception:  # noqa: BLE001 —— 掩码仅为告警抑制，失败不影响功能
            pass
        if len(self._active_idx) < 2:
            raise ValueError(f"chain has too few revolute joints: {len(self._active_idx)}")
        self._lower = np.array(
            [float((lk.bounds or (-np.pi, np.pi))[0]) for lk in self._active_links()]
        )
        self._upper = np.array(
            [float((lk.bounds or (-np.pi, np.pi))[1]) for lk in self._active_links()]
        )
        self._names = [self._links[i].name for i in self._active_idx]

    @staticmethod
    def _urdf_base_elements(urdf_path: Path) -> list[str]:
        """构造 ikpy ``from_urdf_file`` 的 ``base_elements``（link/joint 交替列表）。

        从根 link 出发沿串联臂行走：``[根link, 关节, link, 关节, ...]``，
        截断于首个名称含 "frame" 的 link（工具系；其后为夹爪指，不属臂运动
        学）。列表以该 frame link 结尾使遍历自然终止（其无子关节）。
        """
        root = ET.parse(str(urdf_path)).getroot()
        parent_of: dict[str, str] = {}
        child_joints: dict[str, list[tuple[str, str]]] = {}
        for joint in root.iter("joint"):
            parent = joint.find("parent")
            child = joint.find("child")
            if parent is None or child is None:
                continue
            p, c = parent.get("link") or "", child.get("link") or ""
            parent_of[c] = p
            child_joints.setdefault(p, []).append((joint.get("name") or c, c))
        roots = sorted(l for l in (lk.get("name") for lk in root.iter("link")) if l not in parent_of)
        if not roots:
            raise ValueError("URDF has no root link")
        elements = [roots[0]]
        cur = roots[0]
        while cur in child_joints:
            jname, child = child_joints[cur][0]  # 串联臂：每 link 取第一个子关节
            elements.append(jname)
            elements.append(child)
            if "frame" in child.lower():
                break  # 以 frame link 结尾：其无子关节，遍历自然终止
            cur = child
        return elements

    def _active_links(self) -> list:
        return [self._links[i] for i in self._active_idx]

    def _to_full(self, q: np.ndarray) -> list[float]:
        if len(q) != self.n_joints:
            raise ValueError(f"q length {len(q)} != n_joints {self.n_joints}")
        full = [0.0] * len(self._links)
        for k, i in enumerate(self._active_idx):
            full[i] = float(q[k])
        return full

    # -- KinematicBackend ------------------------------------------------------

    @property
    def n_joints(self) -> int:
        return len(self._active_idx)

    @property
    def joint_names(self) -> list[str]:
        return list(self._names)

    @property
    def joint_lower(self) -> np.ndarray:
        return self._lower.copy()

    @property
    def joint_upper(self) -> np.ndarray:
        return self._upper.copy()

    def fk(self, q: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        frames = self._chain.forward_kinematics(self._to_full(q), full_kinematics=True)
        T = np.asarray(frames[-1], dtype=float)
        return T[:3, 3].copy(), T[:3, :3] @ self._align_R

    def jacobian(self, q: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        frames = self._chain.forward_kinematics(self._to_full(q), full_kinematics=True)
        pe = np.asarray(frames[-1], dtype=float)[:3, 3]
        Jp = np.zeros((3, self.n_joints))
        Jr = np.zeros((3, self.n_joints))
        for k, i in enumerate(self._active_idx):
            T = np.asarray(frames[i], dtype=float)
            axis = np.asarray(getattr(self._links[i], "rotation"), dtype=float)
            axis_world = T[:3, :3] @ axis
            Jp[:, k] = np.cross(axis_world, pe - T[:3, 3])
            Jr[:, k] = axis_world
        return Jp, Jr

    def source_meta(self) -> dict:
        if self._urdf_path is not None:
            return {
                "tier": self.tier,
                "file_sha256_16": _sha16(self._urdf_path),
                "engine": "ikpy chain parsed from URDF",
                "note": "kinematics-only; independent of physics engine",
            }
        return {
            "tier": MODEL_TIER_CHAIN_BUILTIN,
            "file_sha256_16": None,
            "engine": "ikpy builtin nominal chain",
            "note": "nominal constants embedded in source; no model file needed",
        }

# -*- coding: utf-8 -*-
# 自动化打怪脚本
# 主程序 - GUI界面和自动化逻辑

import sys
import os
import threading
import time
import ctypes
import ctypes.wintypes
import traceback
import pyautogui

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'libs'))

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from PIL import Image, ImageTk

from monster_detector import MonsterDetector
from keyboard_controller import KeyboardController, AttackStrategy
from hpmp_detector import HPMPDetector


def get_base_dir():
    """获取程序数据/模板根目录。
    打包后使用 exe 所在目录（而非 _internal），便于用户管理 player/monsters 模板。
    开发调试时使用脚本所在目录。
    """
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包环境：exe 所在目录
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


class MapleStoryBot:
    """自动化打怪脚本主程序"""

    def __init__(self):
        self.running = False
        self.base_dir = get_base_dir()
        # 模板目录统一位于 exe/脚本 所在目录，便于用户管理
        self.detector = MonsterDetector(
            monster_templates_dir=os.path.join(self.base_dir, 'monsters'),
            player_templates_dir=os.path.join(self.base_dir, 'player'),
            wall_templates_dir=os.path.join(self.base_dir, 'wall'),
            throwpoint_templates_dir=os.path.join(self.base_dir, 'throwpoint')
        )
        self.kb_controller = KeyboardController()
        self.attack_strategy = AttackStrategy(self.kb_controller)
        self.hpmp_detector = HPMPDetector()

        self.config = {
            'attack_key': 'a',
            'skill_key': 'd',
            'skill1_key': 'f',
            'jump_key': 'alt',
            'move_left': 'j',
            'move_right': 'k',
            'hp_potion_key': 'delete',   # HP药水键（默认Del）
            'mp_potion_key': 'end',      # MP药水键（默认End）
            'attack_interval': 0.3,
            'threshold': 0.7,
            'player_threshold': 0.7,
            'attack_distance': 400,
            'attack_distance_y': 100,
            'region_margin_left': 100,
            'region_margin_right': 100,
            'skill_cooldown': 9999,
            'skill1_cooldown': 9999,
            'use_capture_region': False,
            'capture_x': 0,
            'capture_y': 0,
            'capture_width': 800,
            'capture_height': 600,
            'hp_potion_percent': 50,
            'mp_potion_percent': 50,
            'use_hpmp_detection': False,
            'hp_region_x1': 0, 'hp_region_y1': 0,
            'hp_region_x2': 0, 'hp_region_y2': 0,
            'mp_region_x1': 0, 'mp_region_y1': 0,
            'mp_region_x2': 0, 'mp_region_y2': 0,
            'use_wall_detection': False,
            'wall_threshold': 0.7,
            'wall_action': 'jump',   # 碰墙动作：'jump'跳跃 / 'turn'转向
            'use_throwpoint_detection': False,
            'throwpoint_threshold': 0.7,
            'throwpoint_distance_left': 100,   # 抛点左距离参数
            'throwpoint_distance_right': 100,  # 抛点右距离参数
            'stationary_attack': False,
            'stationary_use_skill': True,
            'detection_interval': 0.3
        }

        # 打怪状态跟踪：记录"上一帧是否正在攻击怪物"，
        # 用于玩家丢失时决定是否按预测位置继续打怪
        self._was_attacking = False

        # 攻击节流：记录上次发起攻击的时间（用 attack_interval 控制攻击频率）
        self._last_attack_time = 0.0

        # 命令线程已处理到的检测帧（防止同一检测帧被命令线程重复处理丢失逻辑）
        self._last_handled_frame = -1

        # === 双线程共享状态：检测线程(写入) / 命令线程(读取) ===
        self._state_lock = threading.Lock()
        self._detection_thread = None
        self._state = {
            'player_pos': None,      # 玩家坐标 (x, y)
            'player_valid': False,   # 玩家是否被检测到
            'lost_count': 0,         # 连续丢失计数
            'monsters': [],          # 本帧怪物列表（已去重）
            'has_monsters': False,   # 是否存在怪物
            'nearest': None,         # 最近怪信息
            'predicted_pos': None,   # 向量外推预测的玩家位置（丢失时使用）
            'walls': [],             # 本帧墙面列表（启用墙面检测时更新）
            'throwpoint': None,      # 本帧抛点位置（启用抛点检测时更新）(x,y)
            'detect_frame': 0,       # 检测帧计数（每次检测线程更新+1）
            'ready': False,          # 是否已产生第一帧结果
        }

        self.setup_gui()

    def setup_gui(self):
        """创建GUI界面"""
        self.root = tk.Tk()
        self.root.title("自动化打怪脚本")
        self.root.geometry("1000x800")
        self.root.resizable(False, False)

        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        left_frame = ttk.Frame(main_frame, width=450)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))

        right_frame = ttk.Frame(main_frame, width=450)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        status_frame = ttk.LabelFrame(left_frame, text="状态", padding="5")
        status_frame.pack(fill=tk.X, pady=5)

        self.status_var = tk.StringVar(value="未启动")
        self.monster_count_var = tk.StringVar(value="检测到怪物: 0")
        self.attack_count_var = tk.StringVar(value="攻击次数: 0")
        self.player_pos_var = tk.StringVar(value="玩家位置: (0, 0)")
        self.hp_status_var = tk.StringVar(value="HP: --")
        self.mp_status_var = tk.StringVar(value="MP: --")

        status_inner = ttk.Frame(status_frame)
        status_inner.pack(fill=tk.X)

        ttk.Label(status_inner, textvariable=self.status_var, font=('Arial', 12)).pack(side=tk.LEFT, padx=5)
        ttk.Label(status_inner, textvariable=self.monster_count_var).pack(side=tk.LEFT, padx=15)
        ttk.Label(status_inner, textvariable=self.attack_count_var).pack(side=tk.LEFT, padx=15)
        ttk.Label(status_inner, textvariable=self.player_pos_var).pack(side=tk.LEFT, padx=15)

        status_row2 = ttk.Frame(status_frame)
        status_row2.pack(fill=tk.X, pady=2)
        ttk.Label(status_row2, textvariable=self.hp_status_var, foreground='red').pack(side=tk.LEFT, padx=15)
        ttk.Label(status_row2, textvariable=self.mp_status_var, foreground='blue').pack(side=tk.LEFT, padx=15)

        control_frame = ttk.LabelFrame(left_frame, text="控制", padding="5")
        control_frame.pack(fill=tk.X, pady=5)

        row1 = ttk.Frame(control_frame)
        row1.pack(fill=tk.X, pady=2)
        self.start_btn = ttk.Button(row1, text="开始打怪F5", command=self.start_bot)
        self.start_btn.pack(side=tk.LEFT, padx=5)
        self.stop_btn = ttk.Button(row1, text="停止F5", command=self.stop_bot, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=5)
        self.stationary_attack_var = tk.BooleanVar(value=self.config['stationary_attack'])
        ttk.Checkbutton(row1, text="原地攻击", variable=self.stationary_attack_var).pack(side=tk.LEFT, padx=5)
        self.stationary_use_skill_var = tk.BooleanVar(value=self.config['stationary_use_skill'])
        ttk.Checkbutton(row1, text="原地技能", variable=self.stationary_use_skill_var).pack(side=tk.LEFT, padx=5)
        ttk.Button(row1, text="刷新模板", command=self.refresh_templates).pack(side=tk.LEFT, padx=5)

        row2 = ttk.Frame(control_frame)
        row2.pack(fill=tk.X, pady=2)
        ttk.Button(row2, text="测试检测", command=self.test_detection).pack(side=tk.LEFT, padx=5)
        ttk.Button(row2, text="框选截图", command=self.capture_and_save_region).pack(side=tk.LEFT, padx=5)

        key_frame = ttk.LabelFrame(left_frame, text="按键配置", padding="5")
        key_frame.pack(fill=tk.X, pady=5)

        ttk.Label(key_frame, text="攻击键:").grid(row=0, column=0, padx=5, pady=2)
        self.attack_key_var = tk.StringVar(value=self.config['attack_key'])
        ttk.Entry(key_frame, textvariable=self.attack_key_var, width=5).grid(row=0, column=1)

        ttk.Label(key_frame, text="技能键:").grid(row=0, column=2, padx=5, pady=2)
        self.skill_key_var = tk.StringVar(value=self.config['skill_key'])
        ttk.Entry(key_frame, textvariable=self.skill_key_var, width=5).grid(row=0, column=3)

        ttk.Label(key_frame, text="技能键1:").grid(row=0, column=4, padx=5, pady=2)
        self.skill1_key_var = tk.StringVar(value=self.config['skill1_key'])
        ttk.Entry(key_frame, textvariable=self.skill1_key_var, width=5).grid(row=0, column=5)

        jump_keys = ['alt', 'space']
        ttk.Label(key_frame, text="跳跃键:").grid(row=1, column=0, padx=5, pady=2)
        self.jump_key_var = tk.StringVar(value=self.config['jump_key'])
        self.jump_key_combobox = ttk.Combobox(key_frame, textvariable=self.jump_key_var, values=jump_keys, width=6)
        self.jump_key_combobox.grid(row=1, column=1)

        # HP药水键（下拉，默认 Del），放在跳跃键后（右边）
        hp_keys = ['delete']
        ttk.Label(key_frame, text="HP药水键:").grid(row=1, column=2, padx=5, pady=2)
        self.hp_potion_key_var = tk.StringVar(value=self.config['hp_potion_key'])
        self.hp_potion_combobox = ttk.Combobox(key_frame, textvariable=self.hp_potion_key_var,
                                               values=hp_keys, width=6)
        self.hp_potion_combobox.grid(row=1, column=3)

        # MP药水键（下拉，默认 End），放在 HP药水键后（右边）
        mp_keys = ['end']
        ttk.Label(key_frame, text="MP药水键:").grid(row=1, column=4, padx=5, pady=2)
        self.mp_potion_key_var = tk.StringVar(value=self.config['mp_potion_key'])
        self.mp_potion_combobox = ttk.Combobox(key_frame, textvariable=self.mp_potion_key_var,
                                               values=mp_keys, width=6)
        self.mp_potion_combobox.grid(row=1, column=5)

        move_keys = ['arrow_left', 'arrow_right']
        ttk.Label(key_frame, text="左移键:").grid(row=2, column=0, padx=5, pady=2)
        self.move_left_var = tk.StringVar(value='arrow_left')
        self.move_left_combobox = ttk.Combobox(key_frame, textvariable=self.move_left_var, values=move_keys, width=10)
        self.move_left_combobox.grid(row=2, column=1)

        ttk.Label(key_frame, text="右移键:").grid(row=2, column=2, padx=5, pady=2)
        self.move_right_var = tk.StringVar(value='arrow_right')
        self.move_right_combobox = ttk.Combobox(key_frame, textvariable=self.move_right_var, values=move_keys, width=10)
        self.move_right_combobox.grid(row=2, column=3)

        param_frame = ttk.LabelFrame(left_frame, text="参数配置", padding="5")
        param_frame.pack(fill=tk.X, pady=5)

        ttk.Label(param_frame, text="检测频率(秒):").grid(row=0, column=0, padx=5, pady=2)
        self.detection_interval_var = tk.StringVar(value=str(self.config['detection_interval']))
        ttk.Entry(param_frame, textvariable=self.detection_interval_var, width=8).grid(row=0, column=1)

        ttk.Label(param_frame, text="HP药水百分比:").grid(row=0, column=2, padx=5, pady=2)
        self.hp_potion_percent_var = tk.StringVar(value=str(self.config['hp_potion_percent']))
        ttk.Entry(param_frame, textvariable=self.hp_potion_percent_var, width=8).grid(row=0, column=3)

        ttk.Label(param_frame, text="区域边距左:").grid(row=0, column=4, padx=5, pady=2)
        self.region_margin_left_var = tk.StringVar(value=str(self.config['region_margin_left']))
        ttk.Entry(param_frame, textvariable=self.region_margin_left_var, width=8).grid(row=0, column=5)

        ttk.Label(param_frame, text="攻击间隔(秒):").grid(row=1, column=0, padx=5, pady=2)
        self.attack_interval_var = tk.StringVar(value=str(self.config['attack_interval']))
        ttk.Entry(param_frame, textvariable=self.attack_interval_var, width=8).grid(row=1, column=1)

        ttk.Label(param_frame, text="MP药水百分比:").grid(row=1, column=2, padx=5, pady=2)
        self.mp_potion_percent_var = tk.StringVar(value=str(self.config['mp_potion_percent']))
        ttk.Entry(param_frame, textvariable=self.mp_potion_percent_var, width=8).grid(row=1, column=3)

        ttk.Label(param_frame, text="区域边距右:").grid(row=1, column=4, padx=5, pady=2)
        self.region_margin_right_var = tk.StringVar(value=str(self.config['region_margin_right']))
        ttk.Entry(param_frame, textvariable=self.region_margin_right_var, width=8).grid(row=1, column=5)

        ttk.Label(param_frame, text="技能冷却(秒):").grid(row=2, column=0, padx=5, pady=2)
        self.skill_cooldown_var = tk.StringVar(value=str(self.config['skill_cooldown']))
        ttk.Entry(param_frame, textvariable=self.skill_cooldown_var, width=8).grid(row=2, column=1)

        ttk.Label(param_frame, text="技能1冷却(秒):").grid(row=2, column=2, padx=5, pady=2)
        self.skill1_cooldown_var = tk.StringVar(value=str(self.config['skill1_cooldown']))
        ttk.Entry(param_frame, textvariable=self.skill1_cooldown_var, width=8).grid(row=2, column=3)

        ttk.Label(param_frame, text="攻击距离(像素):").grid(row=3, column=0, padx=5, pady=2)
        self.attack_distance_var = tk.StringVar(value=str(self.config['attack_distance']))
        ttk.Entry(param_frame, textvariable=self.attack_distance_var, width=8).grid(row=3, column=1)

        ttk.Label(param_frame, text="攻击距离Y轴:").grid(row=3, column=2, padx=5, pady=2)
        self.attack_distance_y_var = tk.StringVar(value=str(self.config['attack_distance_y']))
        ttk.Entry(param_frame, textvariable=self.attack_distance_y_var, width=8).grid(row=3, column=3)

        player_frame = ttk.LabelFrame(left_frame, text="玩家模板管理", padding="5")
        player_frame.pack(fill=tk.X, pady=5)

        row1 = ttk.Frame(player_frame)
        row1.pack(fill=tk.X, pady=2)
        ttk.Button(row1, text="导入人物图片组", command=self.add_player_group).pack(side=tk.LEFT, padx=5)
        ttk.Button(row1, text="打开玩家模板目录", command=self.open_player_dir).pack(side=tk.LEFT, padx=5)

        row2 = ttk.Frame(player_frame)
        row2.pack(fill=tk.X, pady=2)
        ttk.Label(row2, text="识别阈值(0-1):").pack(side=tk.LEFT, padx=5)
        self.player_threshold_var = tk.StringVar(value=str(self.config['player_threshold']))
        ttk.Entry(row2, textvariable=self.player_threshold_var, width=6).pack(side=tk.LEFT, padx=(0, 10))
        self.player_template_list_var = tk.StringVar(value="已加载模板: 0")
        ttk.Label(row2, textvariable=self.player_template_list_var).pack(side=tk.LEFT, padx=5)

        template_frame = ttk.LabelFrame(right_frame, text="怪物模板管理", padding="5")
        template_frame.pack(fill=tk.X, pady=5)

        row1 = ttk.Frame(template_frame)
        row1.pack(fill=tk.X, pady=2)
        ttk.Button(row1, text="添加怪物图片", command=self.add_monster_template).pack(side=tk.LEFT, padx=5)
        ttk.Button(row1, text="导入怪物图片组", command=self.add_monster_group).pack(side=tk.LEFT, padx=5)
        ttk.Button(row1, text="打开模板目录", command=self.open_template_dir).pack(side=tk.LEFT, padx=5)

        row2 = ttk.Frame(template_frame)
        row2.pack(fill=tk.X, pady=2)
        ttk.Label(row2, text="识别阈值(0-1):").pack(side=tk.LEFT, padx=5)
        self.threshold_var = tk.StringVar(value=str(self.config['threshold']))
        ttk.Entry(row2, textvariable=self.threshold_var, width=6).pack(side=tk.LEFT, padx=(0, 10))
        self.template_list_var = tk.StringVar(value="已加载模板: 0")
        ttk.Label(row2, textvariable=self.template_list_var).pack(side=tk.LEFT, padx=5)

        capture_frame = ttk.LabelFrame(right_frame, text="截图区域设置", padding="3")
        capture_frame.pack(fill=tk.X, pady=3)

        cap_row0 = ttk.Frame(capture_frame)
        cap_row0.pack(fill=tk.X, pady=1)
        self.use_capture_region_var = tk.BooleanVar(value=self.config['use_capture_region'])
        ttk.Checkbutton(cap_row0, text="启用自定义截图区域", variable=self.use_capture_region_var).pack(side=tk.LEFT, padx=3)

        cap_row1 = ttk.Frame(capture_frame)
        cap_row1.pack(fill=tk.X, pady=1)
        ttk.Label(cap_row1, text="X:").pack(side=tk.LEFT, padx=2)
        self.capture_x_var = tk.StringVar(value=str(self.config['capture_x']))
        ttk.Entry(cap_row1, textvariable=self.capture_x_var, width=5).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Label(cap_row1, text="Y:").pack(side=tk.LEFT, padx=2)
        self.capture_y_var = tk.StringVar(value=str(self.config['capture_y']))
        ttk.Entry(cap_row1, textvariable=self.capture_y_var, width=5).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Label(cap_row1, text="宽:").pack(side=tk.LEFT, padx=2)
        self.capture_width_var = tk.StringVar(value=str(self.config['capture_width']))
        ttk.Entry(cap_row1, textvariable=self.capture_width_var, width=5).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Label(cap_row1, text="高:").pack(side=tk.LEFT, padx=2)
        self.capture_height_var = tk.StringVar(value=str(self.config['capture_height']))
        ttk.Entry(cap_row1, textvariable=self.capture_height_var, width=5).pack(side=tk.LEFT, padx=(0, 6))

        cap_row2 = ttk.Frame(capture_frame)
        cap_row2.pack(fill=tk.X, pady=1)
        ttk.Button(cap_row2, text="框选游戏", command=lambda: self._select_screen_region('capture')).pack(side=tk.LEFT, padx=3)
        ttk.Button(cap_row2, text="检测游戏窗口", command=self.detect_game_window).pack(side=tk.LEFT, padx=3)

        # === HP/MP 检测设置 ===
        hpmp_frame = ttk.LabelFrame(right_frame, text="HP/MP 检测设置", padding="3")
        hpmp_frame.pack(fill=tk.X, pady=3)

        hpmp_row0 = ttk.Frame(hpmp_frame)
        hpmp_row0.pack(fill=tk.X, pady=1)
        self.use_hpmp_var = tk.BooleanVar(value=self.config['use_hpmp_detection'])
        ttk.Checkbutton(hpmp_row0, text="启用HP/MP自动检测与喝药", variable=self.use_hpmp_var).pack(side=tk.LEFT, padx=3)

        # HP 区域设置
        hpmp_row1 = ttk.Frame(hpmp_frame)
        hpmp_row1.pack(fill=tk.X, pady=1)
        ttk.Label(hpmp_row1, text="HP区域:").pack(side=tk.LEFT, padx=2)
        self.hp_rx1_var = tk.StringVar(value=str(self.config['hp_region_x1']))
        ttk.Entry(hpmp_row1, textvariable=self.hp_rx1_var, width=4).pack(side=tk.LEFT)
        self.hp_ry1_var = tk.StringVar(value=str(self.config['hp_region_y1']))
        ttk.Label(hpmp_row1, text=",").pack(side=tk.LEFT)
        ttk.Entry(hpmp_row1, textvariable=self.hp_ry1_var, width=4).pack(side=tk.LEFT)
        self.hp_rx2_var = tk.StringVar(value=str(self.config['hp_region_x2']))
        ttk.Label(hpmp_row1, text="~").pack(side=tk.LEFT, padx=1)
        ttk.Entry(hpmp_row1, textvariable=self.hp_rx2_var, width=4).pack(side=tk.LEFT)
        self.hp_ry2_var = tk.StringVar(value=str(self.config['hp_region_y2']))
        ttk.Label(hpmp_row1, text=",").pack(side=tk.LEFT)
        ttk.Entry(hpmp_row1, textvariable=self.hp_ry2_var, width=4).pack(side=tk.LEFT)
        ttk.Button(hpmp_row1, text="框选HP", command=lambda: self._select_screen_region('hp')).pack(side=tk.LEFT, padx=3)

        # MP 区域设置
        hpmp_row2 = ttk.Frame(hpmp_frame)
        hpmp_row2.pack(fill=tk.X, pady=1)
        ttk.Label(hpmp_row2, text="MP区域:").pack(side=tk.LEFT, padx=2)
        self.mp_rx1_var = tk.StringVar(value=str(self.config['mp_region_x1']))
        ttk.Entry(hpmp_row2, textvariable=self.mp_rx1_var, width=4).pack(side=tk.LEFT)
        self.mp_ry1_var = tk.StringVar(value=str(self.config['mp_region_y1']))
        ttk.Label(hpmp_row2, text=",").pack(side=tk.LEFT)
        ttk.Entry(hpmp_row2, textvariable=self.mp_ry1_var, width=4).pack(side=tk.LEFT)
        self.mp_rx2_var = tk.StringVar(value=str(self.config['mp_region_x2']))
        ttk.Label(hpmp_row2, text="~").pack(side=tk.LEFT, padx=1)
        ttk.Entry(hpmp_row2, textvariable=self.mp_rx2_var, width=4).pack(side=tk.LEFT)
        self.mp_ry2_var = tk.StringVar(value=str(self.config['mp_region_y2']))
        ttk.Label(hpmp_row2, text=",").pack(side=tk.LEFT)
        ttk.Entry(hpmp_row2, textvariable=self.mp_ry2_var, width=4).pack(side=tk.LEFT)
        ttk.Button(hpmp_row2, text="框选MP", command=lambda: self._select_screen_region('mp')).pack(side=tk.LEFT, padx=3)

        # 操作按钮
        hpmp_row3 = ttk.Frame(hpmp_frame)
        hpmp_row3.pack(fill=tk.X, pady=1)
        ttk.Button(hpmp_row3, text="测试HP", command=self.test_hp_detection).pack(side=tk.LEFT, padx=3)
        ttk.Button(hpmp_row3, text="测试MP", command=self.test_mp_detection).pack(side=tk.LEFT, padx=3)
        ttk.Button(hpmp_row3, text="校准颜色", command=self.calibrate_hpmp).pack(side=tk.LEFT, padx=3)

        # === 墙面检测（独立大模块） ===
        wall_frame = ttk.LabelFrame(right_frame, text="墙面检测", padding="3")
        wall_frame.pack(fill=tk.X, pady=3)
        self.wall_enable_var = tk.BooleanVar(value=self.config['use_wall_detection'])

        wall_row1 = ttk.Frame(wall_frame)
        wall_row1.pack(fill=tk.X, pady=1)
        ttk.Checkbutton(wall_row1, text="启用墙面检测",
                        variable=self.wall_enable_var).pack(side=tk.LEFT, padx=3)
        ttk.Button(wall_row1, text="导入墙面图片", command=self.add_wall_template).pack(side=tk.LEFT, padx=3)
        ttk.Button(wall_row1, text="打开墙面目录", command=self.open_wall_dir).pack(side=tk.LEFT, padx=3)

        wall_row2 = ttk.Frame(wall_frame)
        wall_row2.pack(fill=tk.X, pady=1)
        ttk.Label(wall_row2, text="识别阈值(0-1):").pack(side=tk.LEFT, padx=3)
        self.wall_threshold_var = tk.StringVar(value=str(self.config['wall_threshold']))
        ttk.Entry(wall_row2, textvariable=self.wall_threshold_var, width=6).pack(side=tk.LEFT, padx=(0, 8))
        self.wall_template_list_var = tk.StringVar(value="已加载模板: 0")
        ttk.Label(wall_row2, textvariable=self.wall_template_list_var).pack(side=tk.LEFT, padx=3)

        # 碰墙动作选项：碰墙后跳跃 或 转向
        wall_row3 = ttk.Frame(wall_frame)
        wall_row3.pack(fill=tk.X, pady=1)
        ttk.Label(wall_row3, text="碰墙动作:").pack(side=tk.LEFT, padx=3)
        wall_action_values = ['碰墙跳跃', '碰墙转向']
        self.wall_action_var = tk.StringVar(
            value='碰墙跳跃' if self.config['wall_action'] == 'jump' else '碰墙转向')
        self.wall_action_combobox = ttk.Combobox(wall_row3, textvariable=self.wall_action_var,
                                                 values=wall_action_values, width=10, state='readonly')
        self.wall_action_combobox.pack(side=tk.LEFT, padx=3)

        # === 原地移动抛点（独立大模块） ===
        tp_frame = ttk.LabelFrame(right_frame, text="原地移动抛点", padding="3")
        tp_frame.pack(fill=tk.X, pady=3)
        self.tp_enable_var = tk.BooleanVar(value=self.config['use_throwpoint_detection'])

        tp_row1 = ttk.Frame(tp_frame)
        tp_row1.pack(fill=tk.X, pady=1)
        ttk.Checkbutton(tp_row1, text="启用原地移动抛点",
                        variable=self.tp_enable_var).pack(side=tk.LEFT, padx=3)
        ttk.Button(tp_row1, text="导入抛点图片", command=self.add_throwpoint_template).pack(side=tk.LEFT, padx=3)
        ttk.Button(tp_row1, text="打开抛点目录", command=self.open_throwpoint_dir).pack(side=tk.LEFT, padx=3)

        tp_row2 = ttk.Frame(tp_frame)
        tp_row2.pack(fill=tk.X, pady=1)
        ttk.Label(tp_row2, text="识别阈值(0-1):").pack(side=tk.LEFT, padx=3)
        self.tp_threshold_var = tk.StringVar(value=str(self.config['throwpoint_threshold']))
        ttk.Entry(tp_row2, textvariable=self.tp_threshold_var, width=6).pack(side=tk.LEFT, padx=(0, 8))
        # 已加载模板数放到识别阈值右边
        self.tp_template_list_var = tk.StringVar(value="已加载模板: 0")
        ttk.Label(tp_row2, textvariable=self.tp_template_list_var).pack(side=tk.LEFT, padx=3)

        # 左/右距离参数：左距离参数在识别阈值下面，右距离参数在左距离右边
        tp_row3 = ttk.Frame(tp_frame)
        tp_row3.pack(fill=tk.X, pady=1)
        ttk.Label(tp_row3, text="左距离(像素):").pack(side=tk.LEFT, padx=3)
        self.tp_distance_left_var = tk.StringVar(value=str(self.config['throwpoint_distance_left']))
        ttk.Entry(tp_row3, textvariable=self.tp_distance_left_var, width=6).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Label(tp_row3, text="右距离(像素):").pack(side=tk.LEFT, padx=3)
        self.tp_distance_right_var = tk.StringVar(value=str(self.config['throwpoint_distance_right']))
        ttk.Entry(tp_row3, textvariable=self.tp_distance_right_var, width=6).pack(side=tk.LEFT, padx=(0, 8))

    def start_bot(self):
        if not self.update_config():
            return
        self.running = True
        self.attack_strategy.reset_count()
        self.attack_strategy.reset_skill_timers()  # 避免启动时立即触发技能
        # 巡逻状态
        self._patrol_direction = 'left'   # 默认向左巡逻
        self._last_player_pos = None      # 上次检测到的玩家位置（用于预测）
        self.detector.player_lost_count = 0  # 重置 detector 的丢失计数
        # 打怪状态
        self._was_attacking = False
        self._last_attack_time = 0.0
        self._last_handled_frame = -1
        # 跳墙状态：记录上次跳墙的检测帧（避免同一帧重复跳）
        self._last_wall_jump_frame = -1
        self._last_wall_jump_time = 0.0
        # 墙面检测触发：仅当人物卡在同一坐标时才进行墙面检测（降低开销）
        self._detect_pos_history = []
        # 黑屏报警：记录上次报警时间，防重复报警
        self._last_black_alert_time = 0.0
        # 重置共享检测状态
        with self._state_lock:
            self._state['player_pos'] = None
            self._state['player_valid'] = False
            self._state['lost_count'] = 0
            self._state['monsters'] = []
            self._state['has_monsters'] = False
            self._state['nearest'] = None
            self._state['predicted_pos'] = None
            self._state['walls'] = []
            self._state['detect_frame'] = 0
            self._state['ready'] = False
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.status_var.set("启动")

        # 启动检测线程（截图/识别）与命令线程（发移动/攻击/技能命令）。
        # 检测线程始终启动：原地攻击/小移动/普通模式都需要检测结果。
        self.bot_thread = threading.Thread(target=self.bot_loop, daemon=True)
        self.bot_thread.start()
        self._detection_thread = threading.Thread(target=self._detection_worker, daemon=True)
        self._detection_thread.start()

    def stop_bot(self):
        self.running = False
        self.kb_controller.release_held_key()  # 释放持续按住的移动键
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.status_var.set("停止")
        self.player_pos_var.set("玩家位置: (0, 0)")
        self.monster_count_var.set("检测到怪物: 0")
        self.attack_count_var.set("攻击次数: 0")
        self.attack_strategy.reset_count()

    def _toggle_bot(self):
        """F5快捷键切换启动/停止"""
        if self.running:
            self.root.after(0, self.stop_bot)
        else:
            self.root.after(0, self.start_bot)

    def _setup_f5_hotkey(self):
        """设置 F5 全局快捷键"""
        try:
            from pynput import keyboard
            self._hotkey_listener = keyboard.GlobalHotKeys({
                '<f5>': self._toggle_bot
            })
            self._hotkey_listener.daemon = True
            self._hotkey_listener.start()
        except Exception as e:
            print(f"F5 快捷键设置失败: {e}")

    def _get_dpi_scale(self):
        """获取DPI缩放因子，用于处理高DPI显示器"""
        try:
            dpi = ctypes.windll.user32.GetDpiForSystem()
            return dpi / 96.0
        except:
            return 1.0
    
    def _screen_to_logical_coords(self, x, y):
        """将屏幕物理坐标转换为逻辑坐标（考虑DPI缩放）"""
        scale = self._get_dpi_scale()
        return int(x / scale), int(y / scale)
    
    def _show_preview(self, screen):
        """弹出窗口预览带标记的截图，1:1 显示，且只复用同一个预览窗口。

        连续点击"测试检测"时，复用同一个窗口，不会弹出多个。
        """
        import cv2
        try:
            from PIL import Image, ImageTk
        except Exception as e:
            print(f"预览失败: {e}")
            return

        screen_rgb = cv2.cvtColor(screen, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(screen_rgb)

        # 复用同一个预览窗口：若已存在则先销毁，避免弹出多个窗口
        if hasattr(self, '_preview_window') and self._preview_window is not None:
            try:
                self._preview_window.destroy()
            except Exception:
                pass
        self._preview_window = tk.Toplevel(self.root)
        self._preview_window.title("测试检测预览")
        self._preview_window.attributes('-topmost', True)

        # 1:1 显示，不缩放
        self._preview_image = ImageTk.PhotoImage(img)  # 保存引用防止被回收
        label = tk.Label(self._preview_window, image=self._preview_image)
        label.pack()

        info = tk.Label(self._preview_window,
                        text="这是带标记的检测结果预览（1:1，玩家红框/怪物绿框/区域紫框等）")
        info.pack(pady=3)

    def _mark_and_save(self, screen, player_info, monsters):
        """在截图上标记玩家(红框)/怪物(绿框)，并询问是否保存截图。"""
        import cv2

        msg_parts = []

        # === 人物移动区域（紫色框） ===
        # 左边界 = 0 + 区域边距左，右边界 = 截图宽 - 区域边距右
        h, w = screen.shape[:2]
        left_x = self.config['region_margin_left']
        right_x = w - self.config['region_margin_right']
        cv2.rectangle(screen, (left_x, 0), (right_x, h), (255, 0, 255), 2)
        cv2.putText(screen, f"移动区域: {left_x} ~ {right_x}", (left_x, 15),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 255), 1)
        msg_parts.append(f"移动区域: 左={left_x} 右={right_x} (左距={self.config['region_margin_left']} 右距={self.config['region_margin_right']})")

        # === 标记玩家（红框） ===
        if player_info:
            print(f"检测到玩家位置: {player_info['position']}")
            bbox = player_info.get('bbox')
            if bbox:
                x1, y1, x2, y2 = bbox
                cv2.rectangle(screen, (int(x1), int(y1)), (int(x2), int(y2)), (0, 0, 255), 2)
                label = f"Player: {player_info['template']} ({player_info['confidence']:.2f})"
                cv2.putText(screen, label, (int(x1), int(y1) - 5),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
            else:
                x, y = player_info['position']
                cv2.circle(screen, (int(x), int(y)), 20, (0, 0, 255), 2)
                label = f"Player: {player_info['template']} ({player_info['confidence']:.2f})"
                cv2.putText(screen, label, (int(x) - 50, int(y) - 25),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
            msg_parts.append(f"玩家: 已检测到 ({player_info['position'][0]:.0f}, {player_info['position'][1]:.0f})")
        else:
            print("未检测到玩家")
            msg_parts.append("玩家: 未检测到")

        # === 标记怪物（绿框） ===
        if monsters:
            print(f"检测到 {len(monsters)} 个怪物")
            for monster in monsters:
                x1, y1, x2, y2 = monster['bbox']
                cv2.rectangle(screen, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 0), 2)
                label = f"{monster['name']}: {monster['confidence']:.2f}"
                cv2.putText(screen, label, (int(x1), int(y1) - 5),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
            msg_parts.append(f"怪物: 检测到 {len(monsters)} 个")
        else:
            print("未检测到怪物")
            msg_parts.append("怪物: 未检测到")

        # 汇总提示
        summary = "\n".join(msg_parts)
        print(f"\n[测试检测结果]\n{summary}")

        # 弹出窗口预览带标记的截图（1:1，不再保存截图）
        self._show_preview(screen)

    def test_detection(self):
        """测试检测：统一临时截图检测一次。

        无论 bot 是否启动，都调用 detect_all_in_one() 截图并检测一次，
        可保存带标记截图（玩家红框、怪物绿框、移动区域紫框、墙面褐框）。
        """
        self.update_config()

        print("临时截图检测一次...")
        region = self._get_capture_region()
        result = self.detector.detect_all_in_one(
            threshold=self.config['threshold'],
            player_threshold=self.config['player_threshold'],
            region=region
        )

        # 若启用墙面检测，检测墙面并在截图上用褐色框标记（叠加到标记图上）
        walls = []
        if self.config['use_wall_detection']:
            walls = self.detector.detect_walls(
                threshold=self.config['wall_threshold'],
                screen=result['screen']
            )
            self._mark_walls(result['screen'], walls)

        # 若启用原地移动抛点，检测抛点并在截图上用黄色框标记
        throwpoints = []
        if self.config['use_throwpoint_detection']:
            throwpoints = self.detector.detect_throwpoint(
                threshold=self.config['throwpoint_threshold'],
                screen=result['screen']
            )
            self._mark_throwpoint(result['screen'], throwpoints)

        self._mark_and_save(
            result['screen'],
            result['player_info'],
            result['monsters'] or []
        )

    def capture_and_save_region(self):
        """框选一个区域，并把该区域的截图保存为图片"""
        self._select_screen_region('screenshot')

    def _update_gui_safe(self, var, value):
        """线程安全地更新GUI变量"""
        try:
            self.root.after(0, lambda: var.set(value))
        except Exception:
            pass

    def _read_state(self):
        """线程安全地读取共享检测状态"""
        with self._state_lock:
            return dict(self._state)

    def _do_move(self, direction):
        """统一移动：持续按住移动键。direction: 'left' 或 'right'。"""
        move_keys = {'left': self.config['move_left'], 'right': self.config['move_right']}
        key = move_keys.get(direction, self.config['move_left'])
        self.kb_controller.hold_key_continuous(key)

    def _check_wall_jump(self, player_pos, walls, patrol_dir, detect_frame, move_keys=None):
        """巡逻时判断人物是否碰撞墙面，碰墙后根据配置执行跳跃或转向。

        直接用检测线程实时检测到的墙面数据（walls）判断碰撞，不记录预测历史坐标。
        返回 True 表示执行了跳跃/转向。
        """
        if player_pos is None:
            return False

        # 跳跃节流：同一检测帧只判断一次；且跳跃之间至少间隔一段时间（防连续跳）
        if detect_frame == self._last_wall_jump_frame:
            return False
        if time.time() - self._last_wall_jump_time < 0.5:
            self._last_wall_jump_frame = detect_frame
            return False

        px, py = player_pos
        tol_x = 50   # 人物与墙面中心的水平碰撞阈值
        tol_y = 50   # 人物与墙面中心的垂直碰撞阈值

        # 直接用实时检测到的墙面数据判断碰撞（不记录/复用预测历史坐标）
        for wall in (walls or []):
            x1, y1, x2, y2 = wall['bbox']
            wall_cx = (x1 + x2) / 2.0
            wall_cy = (y1 + y2) / 2.0
            if abs(wall_cx - px) <= tol_x and abs(wall_cy - py) <= tol_y:
                self._last_wall_jump_frame = detect_frame
                self._last_wall_jump_time = time.time()

                # 根据碰墙动作选项执行：跳跃 或 转向
                if self.config.get('wall_action', 'jump') == 'jump':
                    # 碰墙跳跃：按跳跃键
                    self.kb_controller.press_key(self.config['jump_key'], 0.1)
                    print(f"[碰墙] 巡逻 {patrol_dir} 碰撞墙面，跳跃跳过 (墙: ({int(wall_cx)},{int(wall_cy)}))")
                else:
                    # 碰墙转向：反向巡逻
                    if move_keys is None:
                        move_keys = {'left': self.config['move_left'], 'right': self.config['move_right']}
                    back_dir = 'right' if patrol_dir == 'left' else 'left'
                    self._patrol_direction = back_dir
                    self.kb_controller.release_held_key()
                    self._do_move(back_dir)
                    print(f"[碰墙] 巡逻 {patrol_dir} 碰撞墙面，转向: {back_dir} (墙: ({int(wall_cx)},{int(wall_cy)}))")

                # 碰墙后刷新墙面检测的位置历史，重新累计（跳跃/转向后需要重新判定卡住）
                self._detect_pos_history.clear()
                return True
        return False

    def _check_black_screen(self, screen):
        """检测屏幕是否黑屏（掉线前会黑屏），若是则触发一次报警音效。

        判定标准：黑色像素（亮度<30）占整个画面比例超过 70% 视为黑屏。
        播放软件目录 sound/ 下的音频文件（如 alert.wav）；文件不存在则回退到 Windows 系统提示音。
        防重复：两次报警间隔至少 10 秒。
        """
        try:
            import winsound
            import numpy as np
            gray = np.asarray(screen).mean(axis=2)  # 每个像素的平均亮度 (H, W)
            black_ratio = float((gray < 30).mean())  # 黑色像素占比
            if black_ratio > 0.70:
                now = time.time()
                if now - self._last_black_alert_time > 10:
                    self._last_black_alert_time = now
                    # 播放软件目录 sound/ 下的报警音频（若存在），否则回退系统提示音
                    sound_path = os.path.join(self.base_dir, 'sound', 'alert.wav')
                    if os.path.exists(sound_path):
                        winsound.PlaySound(sound_path, winsound.SND_FILENAME)
                    else:
                        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
                    print(f"[黑屏报警] 检测到黑屏（黑色占比={black_ratio*100:.1f}%），已报警！")
        except Exception as e:
            # 报警失败不影响其他检测逻辑
            print(f"[黑屏报警] 报警异常: {e}")

    def _do_detect(self):
        """执行一次完整检测：截图 + 检测玩家/怪物/墙面/抛点，结果写入共享状态。

        供检测线程（_detection_worker）与小移动单线程模式（bot_loop）复用。
        """
        region = self._get_capture_region()
        result = self.detector.detect_all_in_one(
            threshold=self.config['threshold'],
            player_threshold=self.config['player_threshold'],
            region=region
        )

        player_info = result['player_info']
        monsters = result['monsters'] or []

        # 黑屏检测（掉线前会黑屏）：仅当玩家丢失（人物检测不到）时才检查，减少开销
        if player_info is None:
            self._check_black_screen(result['screen'])

        # 计算最近怪
        nearest = None
        if monsters:
            base_pos = player_info['position'] if player_info else None
            if base_pos is None:
                with self._state_lock:
                    base_pos = self._state.get('player_pos')
            if base_pos is not None:
                nearest = self.detector.find_nearest_monster(
                    base_pos, monsters,
                    y_tolerance=self.config['attack_distance_y']
                )

        lost_count = self.detector.player_lost_count
        player_valid = player_info is not None

        # 向量外推预测位置
        predicted_pos = self.detector.predict_player_pos()

        # === 墙面检测（降低开销：人物疑似卡住时立即检测） ===
        walls = []
        if self.config['use_wall_detection']:
            if player_info is not None:
                pos = player_info['position']
                self._detect_pos_history.append(pos)
                if len(self._detect_pos_history) > 10:
                    self._detect_pos_history.pop(0)
            else:
                self._detect_pos_history.clear()

            # 判定人物是否疑似卡住：对比上一个坐标，前后8像素内都算卡住
            stuck = False
            if len(self._detect_pos_history) >= 2:
                prev = self._detect_pos_history[-2]
                cur = self._detect_pos_history[-1]
                if abs(cur[0] - prev[0]) <= 8 and abs(cur[1] - prev[1]) <= 8:
                    stuck = True

            # 判定为卡住后立即执行墙面检测
            if stuck:
                walls = self.detector.detect_walls(
                    threshold=self.config['wall_threshold'],
                    screen=result['screen']
                )

        # === 抛点检测（原地移动抛点）：启用时检测抛点位置 ===
        throwpoint = None
        if self.config['use_throwpoint_detection']:
            def _valid_pos(p):
                """校验抛点坐标是否为合法数字。兼容 np.int64/np.float64 等类型，
                仅排除非数字/非正数等明显非法值。"""
                if p is None or not isinstance(p, (tuple, list)) or len(p) < 2:
                    return False
                x, y = p[0], p[1]
                # 兼容 Python int/float 以及 numpy 整数/浮点类型
                try:
                    x = float(x)
                    y = float(y)
                except (TypeError, ValueError):
                    return False
                # 排除 0/负数 等明显非法值
                if x <= 0 or y <= 0:
                    return False
                return True

            try:
                tp_list = self.detector.detect_throwpoint(
                    threshold=self.config['throwpoint_threshold'],
                    screen=result['screen']
                )
            except Exception as e:
                # 抛点检测异常（如模板比截图大、截图异常等）：不影响其他检测，抛点记为丢失
                print(f"[抛点检测] 异常: {e}")
                tp_list = []

            # 过滤掉非法坐标的抛点
            tp_list = [tp for tp in (tp_list or []) if _valid_pos(tp.get('position'))]

            chosen = None
            if tp_list:
                # 优先选择人物Y上下200以内的抛点图片（|人物Y - 抛点Y| <= 200），
                # 避免取到人物Y范围外的抛点导致位置错误；没有符合的再取置信度最高者。
                if player_info is not None:
                    py = player_info['position'][1]
                    for tp in tp_list:
                        tp_y = tp['position'][1]
                        if abs(tp_y - py) <= 200:
                            chosen = tp
                            break
                if chosen is None:
                    chosen = tp_list[0]
                throwpoint = chosen['position']
            # else：检测丢失或无合法抛点 → throwpoint 保持 None（抛点丢失，暂停行动）

        with self._state_lock:
            self._state['player_pos'] = player_info['position'] if player_info else None
            self._state['player_valid'] = player_valid
            self._state['lost_count'] = lost_count
            self._state['monsters'] = monsters
            self._state['has_monsters'] = len(monsters) > 0
            self._state['nearest'] = nearest
            self._state['predicted_pos'] = predicted_pos
            self._state['walls'] = walls
            self._state['throwpoint'] = throwpoint
            self._state['detect_frame'] += 1
            self._state['ready'] = True

        # 更新 GUI 怪物计数
        self._update_gui_safe(self.monster_count_var, f"检测到怪物: {len(monsters)}")

    def _detection_worker(self):
        """检测线程：持续截图并检测玩家/怪物，将结果写入共享状态。

        只做图像检测，不发送任何键盘命令；命令线程（bot_loop）负责发命令。
        一次截图同时检测玩家和怪物，避免重复截图，提高检测频率。
        """
        while self.running:
            try:
                self._do_detect()
                # 控制检测频率
                time.sleep(self.config['detection_interval'])
            except Exception as e:
                print(f"[检测线程] 错误: {e}")
                traceback.print_exc()
                time.sleep(1)

    def bot_loop(self):
        while self.running:
            try:
                attack_distance = self.config['attack_distance']
                attack_distance_y = self.config['attack_distance_y']
                move_keys = {
                    'left': self.config['move_left'],
                    'right': self.config['move_right']
                }

                # === 1. 读取检测线程的最新结果 ===
                state = self._read_state()
                player_pos = state['player_pos']
                player_valid = state['player_valid']
                lost_count = state['lost_count']
                nearest = state['nearest']
                predicted_pos = state['predicted_pos']
                walls = state['walls']
                throwpoint = state['throwpoint']
                detect_frame = state['detect_frame']

                # 未产生第一帧结果时先等待检测线程（多线程模式需要；单线程模式已有结果）
                if not state['ready']:
                    time.sleep(0.05)
                    continue

                # 兜底：玩家当前检测不到时，用预测位置或最后位置补齐 player_pos，
                # 保证后续边界检测/攻击决策不会因 player_pos 为 None 而崩溃。
                if player_pos is None:
                    if predicted_pos is not None:
                        player_pos = predicted_pos
                    elif self._last_player_pos is not None:
                        player_pos = self._last_player_pos

                if player_valid and player_pos is not None:
                    self._last_player_pos = player_pos
                    self._last_handled_frame = detect_frame
                    self._update_gui_safe(self.player_pos_var,
                        f"玩家位置: ({int(player_pos[0])}, {int(player_pos[1])})")
                elif self._last_player_pos is not None:
                    # 玩家丢失：优先使用向量外推的预测位置（更贴合真实运动），否则用最后位置
                    # 注意：命令线程每0.02s轮询，检测线程按 detection_interval 更新 lost_count，
                    # 同一检测帧会被命令线程轮询多次。必须只在检测帧变化时处理一次，
                    # 避免"开始寻找/第10次"被重复打印，也避免方向被反复切换。
                    if detect_frame != self._last_handled_frame:
                        self._last_handled_frame = detect_frame

                        if predicted_pos is not None:
                            player_pos = predicted_pos
                            self._last_player_pos = player_pos
                            self._update_gui_safe(self.player_pos_var, f"玩家位置: 丢失({lost_count})预测")
                        else:
                            player_pos = self._last_player_pos
                            self._update_gui_safe(self.player_pos_var, f"玩家位置: 丢失({lost_count})")

                        # 玩家丢失：仅原地攻击/抛点模式下禁止移动；普通模式继续行动
                        if self.stationary_attack_var.get() or self.config['use_throwpoint_detection']:
                            self.kb_controller.release_held_key()
                            if lost_count == 1:
                                print(f"[玩家丢失] 丢失({lost_count})，停止移动，等待下次检测")
                        elif lost_count == 1:
                            print(f"[玩家丢失] 丢失({lost_count})，继续巡逻/打怪")
                else:
                    # 首次未检测到玩家且无历史记录：仅原地攻击/抛点模式禁止移动，普通模式继续
                    player_pos = (0, 0)
                    self._last_player_pos = player_pos
                    self._update_gui_safe(self.player_pos_var, f"玩家位置: 丢失({lost_count})")
                    if self.stationary_attack_var.get() or self.config['use_throwpoint_detection']:
                        self.kb_controller.release_held_key()
                        print(f"[玩家丢失] 首次未检测，停止移动，等待下次检测")

                # === 1.5 自动使用技能（独立于怪物检测，冷却到就释放） ===
                self.attack_strategy.try_use_skills()

                # === 1.6 HP/MP 检测与自动喝药 ===
                if self.config['use_hpmp_detection']:
                    hp_percent = self.hpmp_detector.detect_hp()
                    mp_percent = self.hpmp_detector.detect_mp()

                    if hp_percent is not None:
                        self._update_gui_safe(self.hp_status_var, f"HP: {hp_percent:.0f}%")
                        if hp_percent < self.config['hp_potion_percent']:
                            self.kb_controller.press_key(self.config['hp_potion_key'], 0.05)
                    else:
                        self._update_gui_safe(self.hp_status_var, "HP: --")

                    if mp_percent is not None:
                        self._update_gui_safe(self.mp_status_var, f"MP: {mp_percent:.0f}%")
                        if mp_percent < self.config['mp_potion_percent']:
                            self.kb_controller.press_key(self.config['mp_potion_key'], 0.05)
                    else:
                        self._update_gui_safe(self.mp_status_var, "MP: --")

                # === 1.7 原地攻击模式 ===
                # 范围内有怪物时攻击，不移动（不追击怪物）。若开启抛点且人物不在抛点
                # 安全范围（X：抛点X ± 抛点左/右距离，Y：±100）内，则先移动到抛点，到达后继续原地攻击。
                # 原地攻击为独立分支（continue），不走巡逻的抛点左/右边界逻辑，避免功能重合冲突。
                if self.stationary_attack_var.get():
                    self._was_attacking = False
                    in_tp_range = True
                    # 抛点协同：人物不在抛点安全范围内 → 向抛点移动
                    if (self.config['use_throwpoint_detection'] and throwpoint is not None
                            and player_pos is not None):
                        tp_x, tp_y = throwpoint
                        # 原地攻击回抛点安全区：X 用 throwpoint_distance_left/right，Y 用 ±100
                        tp_left = tp_x - self.config['throwpoint_distance_left']
                        tp_right = tp_x + self.config['throwpoint_distance_right']
                        if not (tp_left <= player_pos[0] <= tp_right
                                and abs(player_pos[1] - tp_y) <= 100):
                            in_tp_range = False
                            # 回抛点用"短步"移动：每次短按一小步，避免持续按住冲过头越过抛点。
                            # 结合检测频率，逐步接近抛点，到达安全范围后停止。
                            self.kb_controller.release_held_key()
                            move_keys_tp = {'left': self.config['move_left'],
                                            'right': self.config['move_right']}
                            if player_pos[0] < tp_x:
                                self.kb_controller.press_key(move_keys_tp['right'], 0.4)
                            elif player_pos[0] > tp_x:
                                self.kb_controller.press_key(move_keys_tp['left'], 0.4)
                            print(f"[原地攻击-回抛点] 人物({int(player_pos[0])},{int(player_pos[1])}) "
                                  f"不在抛点安全范围，短步向抛点移动")
                    # 在抛点范围内（或未启用抛点）：范围内有怪则攻击，否则原地不动
                    if in_tp_range:
                        if nearest is not None and player_pos is not None:
                            px0, py0 = player_pos
                            mx, my = nearest['position']
                            if abs(mx - px0) < attack_distance and abs(my - py0) <= attack_distance_y:
                                now = time.time()
                                if now - self._last_attack_time >= self.config['attack_interval']:
                                    self.kb_controller.release_held_key()
                                    self.kb_controller.turn_direction(player_pos, nearest['position'], move_keys)
                                    self.attack_strategy.execute_attack(abs(mx - px0))
                                    self._last_attack_time = time.time()
                                self._was_attacking = True
                            else:
                                self.kb_controller.release_held_key()
                        else:
                            self.kb_controller.release_held_key()
                    # 原地攻击模式：快速轮询，让攻击频率由 attack_interval 控制，
                    # 而不是被 detection_interval 拖慢（否则攻击频率会偏低）。
                    time.sleep(0.02)
                    continue

                # === 2. 移动区域/边界检测（只计算区域信息，不立即转向，攻击优先） ===
                # 人物超过移动区域（左=区域边距左，右=宽-区域边距右）时应回区域。
                # 优先用预测位置（向量外推）判断，降低截图延迟的影响；
                # 玩家丢失时也用兜底后的 player_pos（预测/最后位置）判断，防止走出区域。
                # 注意：这里只计算 near_boundary / 区域边界，不立即执行转向移动，
                #       以便"攻击范围内有怪优先攻击"；无怪可打时再由转向逻辑回区域。
                near_boundary = False
                judge_x = None
                region_left = 0
                region_right = 0
                capture_width = self.config['capture_width'] if self.config['use_capture_region'] else 1024
                if player_pos is not None:
                    # 边界判断优先使用预测位置（更贴近运动趋势），无预测则用当前/兜底位置
                    if predicted_pos is not None:
                        judge_x = predicted_pos[0]
                    else:
                        judge_x = player_pos[0]

                    region_left = self.config['region_margin_left']
                    region_right = capture_width - self.config['region_margin_right']

                    if judge_x < region_left:
                        near_boundary = True
                    elif judge_x > region_right:
                        near_boundary = True

                # === 3/4. 攻击/移动决策（怪物与最近怪已由检测线程算好） ===
                # 优先级：
                #   1) 有怪且攻击范围内能打到 → 攻击（无视区域外，攻击不移动，安全）
                #   2) 有怪但够不到 → 朝怪移动；若追怪会跑出区域则放弃追，回区域
                #   3) 无怪 → 在区域外则回区域；在区域内则左右巡逻
                # 执行前提：玩家正常检测到，或丢失但前一刻在打怪（继续打怪）
                if (lost_count == 0 or self._was_attacking):
                    # 玩家丢失时，仅原地攻击或抛点模式下暂停行动（等待下次检测）；
                    # 普通巡逻模式（无抛点、无原地攻击）下继续用预测位置正常巡逻/打怪/追击。
                    if lost_count > 0 and (self.stationary_attack_var.get()
                                           or self.config['use_throwpoint_detection']):
                        self._was_attacking = False
                        self.kb_controller.release_held_key()
                        self._update_gui_safe(self.player_pos_var,
                            f"玩家位置: 丢失({lost_count})-等待检测")
                        time.sleep(0.02)
                        continue

                    # 启用抛点但抛点坐标丢失：暂停行动，等待下次检测恢复（抛点逻辑不执行）
                    if self.config['use_throwpoint_detection'] and throwpoint is None:
                        self._was_attacking = False
                        self.kb_controller.release_held_key()
                        time.sleep(0.02)
                        continue

                    # 防御：无玩家位置则跳过本帧攻击决策，避免解包 None 崩溃
                    if player_pos is None:
                        self._was_attacking = False
                    # 玩家丢失用预测位置继续攻击时，若预测位置超出安全区（区域/抛点边界），
                    # 只调整巡逻方向朝抛点（或区域中心），移动交给后续巡逻逻辑执行，
                    # 而不是执行独立的"回安全区"移动。
                    elif lost_count > 0 and (
                            player_pos[0] < region_left or player_pos[0] > region_right
                            or (self.config['use_throwpoint_detection'] and throwpoint is not None
                                and (player_pos[0] < throwpoint[0] - self.config['throwpoint_distance_left']
                                     or player_pos[0] > throwpoint[0] + self.config['throwpoint_distance_right']))):
                        self._was_attacking = False
                        # 调整巡逻方向：优先朝抛点方向，其次朝区域中心
                        if (self.config['use_throwpoint_detection'] and throwpoint is not None
                                and player_pos[0] > throwpoint[0] + self.config['throwpoint_distance_right']):
                            self._patrol_direction = 'left'   # 超出抛点右边界，朝抛点(左)方向
                        elif (self.config['use_throwpoint_detection'] and throwpoint is not None
                              and player_pos[0] < throwpoint[0] - self.config['throwpoint_distance_left']):
                            self._patrol_direction = 'right'  # 超出抛点左边界，朝抛点(右)方向
                        elif player_pos[0] < region_left:
                            self._patrol_direction = 'right'  # 超出区域左边界，朝区域中心
                        elif player_pos[0] > region_right:
                            self._patrol_direction = 'left'   # 超出区域右边界，朝区域中心
                        print(f"[丢失调向] 预测位置({int(player_pos[0])},{int(player_pos[1])})超出安全区，"
                              f"巡逻方向朝 {self._patrol_direction}")
                        # 按调整后的方向巡逻移动（朝抛点/区域中心）
                        self._do_move(self._patrol_direction)
                    elif nearest:
                        px, py_pos = player_pos
                        mx, my = nearest['position']
                        x_distance = abs(mx - px)
                        y_distance = abs(my - py_pos)

                        if x_distance < attack_distance and y_distance <= attack_distance_y:
                            # === 情况1：攻击范围内 → 优先攻击（无视是否在区域外） ===
                            # 用 attack_interval 节流攻击频率，避免命令线程短轮询导致攻击过频
                            now = time.time()
                            if now - self._last_attack_time >= self.config['attack_interval']:
                                self.kb_controller.release_held_key()
                                self.kb_controller.turn_direction(
                                    player_pos, nearest['position'], move_keys
                                )
                                self.attack_strategy.execute_attack(x_distance)
                                self._last_attack_time = time.time()
                            # 正在攻击：记录打怪状态（供丢失时继续打怪）
                            self._was_attacking = True
                        else:
                            # === 情况2：够不到，靠近怪物移动 ===
                            # 追怪不能超过抛点限制，也不能超过区域边距限制：
                            # 若追怪方向会导致人物超出抛点边界或区域边界，则放弃追怪，反向回安全区。
                            self._was_attacking = False
                            # 判断用位置：优先用预测位置，降低延迟影响
                            px_judge = predicted_pos[0] if predicted_pos is not None else px

                            # 计算抛点边界（启用抛点且抛点有效时）：左边界用左距离，右边界用右距离
                            tp_left_edge = tp_right_edge = None
                            if (self.config['use_throwpoint_detection'] and throwpoint is not None):
                                tp_left_edge = throwpoint[0] - self.config['throwpoint_distance_left']
                                tp_right_edge = throwpoint[0] + self.config['throwpoint_distance_right']

                            if mx > px:
                                # 怪物在右侧：只有未到右边界（区域/抛点）才追，否则反向回安全区
                                over_right = px_judge >= region_right
                                if tp_right_edge is not None and px_judge >= tp_right_edge:
                                    over_right = True
                                if over_right:
                                    self._do_move('left')
                                else:
                                    self._do_move('right')
                            elif mx < px:
                                # 怪物在左侧：只有未到左边界（区域/抛点）才追，否则反向回安全区
                                over_left = px_judge <= region_left
                                if tp_left_edge is not None and px_judge <= tp_left_edge:
                                    over_left = True
                                if over_left:
                                    self._do_move('right')
                                else:
                                    self._do_move('left')
                    else:
                        # === 情况3：无怪物 ===
                        self._was_attacking = False

                        # === 3.0 原地移动抛点：只负责修改巡逻方向，不单独控制人物移动 ===
                        # 边界 = 抛点X ± 距离参数D。超出左边界则巡逻方向改为右，超出右边界则改为左，
                        # 边界内按当前方向继续走（穿过抛点）。抛点方向优先于回区域，避免被覆盖。
                        # 未检测到抛点图片则不执行，走正常巡逻/回区域逻辑。
                        tp_active = (self.config['use_throwpoint_detection']
                                     and throwpoint is not None and player_pos is not None)
                        if tp_active:
                            tp_x = throwpoint[0]
                            px = player_pos[0]
                            # 左边界用左距离，右边界用右距离
                            left_edge = tp_x - self.config['throwpoint_distance_left']
                            right_edge = tp_x + self.config['throwpoint_distance_right']

                            if px < left_edge:
                                # 超出左边界 → 巡逻方向改为右（穿过抛点到右侧）
                                if self._patrol_direction != 'right':
                                    self._patrol_direction = 'right'
                                    print(f"[抛点] 超出左边界({int(px)} < {int(left_edge)})，巡逻方向改为右")
                            elif px > right_edge:
                                # 超出右边界 → 巡逻方向改为左（穿过抛点到左侧）
                                if self._patrol_direction != 'left':
                                    self._patrol_direction = 'left'
                                    print(f"[抛点] 超出右边界({int(px)} > {int(right_edge)})，巡逻方向改为左")
                            # 边界内：不修改方向，按当前方向继续走（穿过抛点）
                            # 抛点模式启用时，直接按方向移动（复用巡逻移动逻辑，含跳墙），
                            # 回区域逻辑让位于抛点方向，避免抛点方向被覆盖导致到不了抛点另一侧。
                            self._check_wall_jump(
                                player_pos, walls, self._patrol_direction, detect_frame, move_keys
                            )
                            if self._patrol_direction == 'left':
                                self._do_move('left')
                            else:
                                self._do_move('right')
                        elif near_boundary and judge_x is not None:
                            # 人物在区域外：转向回区域（朝区域中心方向）
                            back_dir = 'right' if judge_x < region_left else 'left'
                            self._patrol_direction = back_dir
                            self._do_move(back_dir)
                            print(f"[回区域] 人物在区域外(judge_x={int(judge_x)})，转向: {back_dir}")
                        else:
                            # 人物在区域内：左右巡逻
                            # 巡逻时若前方有墙面且距离<=50，碰墙后根据选项跳跃或转向
                            self._check_wall_jump(
                                player_pos, walls, self._patrol_direction, detect_frame, move_keys
                            )
                            if self._patrol_direction == 'left':
                                self._do_move('left')
                            else:
                                self._do_move('right')

                # === 5. 更新攻击计数 ===
                self._update_gui_safe(self.attack_count_var,
                    f"攻击次数: {self.attack_strategy.get_attack_count()}")

                # === 命令线程节奏 ===
                # 使用短间隔快速响应检测结果（检测线程负责截图/匹配）。
                time.sleep(0.02)

            except Exception as e:
                print(f"错误: {e}")
                traceback.print_exc()
                time.sleep(1)

    def update_config(self):
        """更新配置，返回True表示成功，False表示输入有误"""
        try:
            self.config['attack_key'] = self.attack_key_var.get()
            self.config['skill_key'] = self.skill_key_var.get()
            self.config['skill1_key'] = self.skill1_key_var.get()
            self.config['jump_key'] = self.jump_key_var.get()
            self.config['hp_potion_key'] = self.hp_potion_key_var.get()
            self.config['mp_potion_key'] = self.mp_potion_key_var.get()
            self.config['move_left'] = self.move_left_var.get()
            self.config['move_right'] = self.move_right_var.get()
            self.config['threshold'] = float(self.threshold_var.get())
            self.config['player_threshold'] = float(self.player_threshold_var.get())
            self.config['attack_interval'] = float(self.attack_interval_var.get())
            self.config['detection_interval'] = float(self.detection_interval_var.get())
            self.config['hp_potion_percent'] = int(self.hp_potion_percent_var.get())
            self.config['mp_potion_percent'] = int(self.mp_potion_percent_var.get())
            self.config['skill_cooldown'] = int(self.skill_cooldown_var.get())
            self.config['skill1_cooldown'] = int(self.skill1_cooldown_var.get())
            self.config['attack_distance'] = int(self.attack_distance_var.get())
            self.config['attack_distance_y'] = int(self.attack_distance_y_var.get())
            self.config['region_margin_left'] = int(self.region_margin_left_var.get())
            self.config['region_margin_right'] = int(self.region_margin_right_var.get())
            
            self.config['use_capture_region'] = self.use_capture_region_var.get()
            self.config['capture_x'] = int(self.capture_x_var.get())
            self.config['capture_y'] = int(self.capture_y_var.get())
            self.config['capture_width'] = int(self.capture_width_var.get())
            self.config['capture_height'] = int(self.capture_height_var.get())

            # HP/MP 检测配置
            self.config['use_hpmp_detection'] = self.use_hpmp_var.get()
            self.config['hp_region_x1'] = int(self.hp_rx1_var.get())
            self.config['hp_region_y1'] = int(self.hp_ry1_var.get())
            self.config['hp_region_x2'] = int(self.hp_rx2_var.get())
            self.config['hp_region_y2'] = int(self.hp_ry2_var.get())
            self.config['mp_region_x1'] = int(self.mp_rx1_var.get())
            self.config['mp_region_y1'] = int(self.mp_ry1_var.get())
            self.config['mp_region_x2'] = int(self.mp_rx2_var.get())
            self.config['mp_region_y2'] = int(self.mp_ry2_var.get())

            # 墙面检测配置
            self.config['use_wall_detection'] = self.wall_enable_var.get()
            self.config['wall_threshold'] = float(self.wall_threshold_var.get())
            # 碰墙动作：根据下拉框文本映射为 'jump'(碰墙跳跃) / 'turn'(碰墙转向)
            self.config['wall_action'] = 'jump' if self.wall_action_var.get() == '碰墙跳跃' else 'turn'

            # 抛点检测配置（原地移动抛点）
            self.config['use_throwpoint_detection'] = self.tp_enable_var.get()
            self.config['throwpoint_threshold'] = float(self.tp_threshold_var.get())
            self.config['throwpoint_distance_left'] = int(self.tp_distance_left_var.get())
            self.config['throwpoint_distance_right'] = int(self.tp_distance_right_var.get())

            # 更新 HP/MP 检测器区域
            if self.config['hp_region_x2'] > self.config['hp_region_x1'] and \
               self.config['hp_region_y2'] > self.config['hp_region_y1']:
                self.hpmp_detector.set_hp_region((
                    self.config['hp_region_x1'], self.config['hp_region_y1'],
                    self.config['hp_region_x2'], self.config['hp_region_y2']
                ))
            if self.config['mp_region_x2'] > self.config['mp_region_x1'] and \
               self.config['mp_region_y2'] > self.config['mp_region_y1']:
                self.hpmp_detector.set_mp_region((
                    self.config['mp_region_x1'], self.config['mp_region_y1'],
                    self.config['mp_region_x2'], self.config['mp_region_y2']
                ))

            self.attack_strategy.set_attack_keys(
                self.config['attack_key'],
                self.config['skill_key'],
                self.config['skill1_key']
            )
            self.attack_strategy.set_attack_distance(self.config['attack_distance'])
            self.attack_strategy.set_skill_cooldown(self.config['skill_cooldown'])
            self.attack_strategy.set_skill1_cooldown(self.config['skill1_cooldown'])
            return True
        except (ValueError, TypeError) as e:
            messagebox.showerror("配置错误", f"参数输入有误，请检查数值格式:\n{e}")
            return False
    
    def _get_capture_region(self):
        """获取截图区域"""
        if self.config['use_capture_region']:
            return (
                self.config['capture_x'],
                self.config['capture_y'],
                self.config['capture_x'] + self.config['capture_width'],
                self.config['capture_y'] + self.config['capture_height']
            )
        return None
    
    def detect_game_window(self):
        """尝试检测游戏窗口（支持多个窗口标题，依次查找，兼容新老版本）"""
        # 依次尝试的窗口标题：优先冒险岛怀旧服，找不到再回退到旧版 MapleStory
        window_titles = ["冒险岛怀旧服", "MapleStory"]
        try:
            hwnd = None
            found_title = None
            for title in window_titles:
                hwnd = ctypes.windll.user32.FindWindowW(None, title)
                if hwnd:
                    found_title = title
                    break

            if hwnd:
                rect = ctypes.wintypes.RECT()
                ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
                self.capture_x_var.set(str(rect.left))
                self.capture_y_var.set(str(rect.top))
                self.capture_width_var.set(str(rect.right - rect.left))
                self.capture_height_var.set(str(rect.bottom - rect.top))
                self.use_capture_region_var.set(True)
                messagebox.showinfo("成功", f"已检测到游戏窗口 [{found_title}]:\n位置: ({rect.left}, {rect.top})\n大小: {rect.right-rect.left} x {rect.bottom-rect.top}")
            else:
                messagebox.showwarning("提示", "未找到游戏窗口（尝试查找: " + "、".join(window_titles) + "），请手动设置区域")
        except Exception as e:
            messagebox.showerror("错误", f"检测游戏窗口失败: {e}")

    def refresh_templates(self):
        self.detector.load_templates()
        self.detector.load_player_templates()
        self.detector.load_wall_templates()
        self.detector.load_throwpoint_templates()
        self.template_list_var.set(f"已加载模板: {len(self.detector.templates)}")
        self.player_template_list_var.set(f"已加载模板: {self.detector.get_player_template_count()}")
        self.wall_template_list_var.set(f"已加载模板: {self.detector.get_wall_template_count()}")
        self.tp_template_list_var.set(f"已加载模板: {self.detector.get_throwpoint_template_count()}")

    def add_monster_template(self):
        file_path = filedialog.askopenfilename(
            title="选择怪物图片",
            filetypes=[("PNG图片", "*.png"), ("JPG图片", "*.jpg"), ("所有文件", "*.*")]
        )
        if file_path:
            self.detector.add_template(file_path)
            self.template_list_var.set(f"已加载模板: {len(self.detector.templates)}")

    def add_player_group(self):
        file_paths = filedialog.askopenfilenames(
            title="选择人物图片组（可多选）",
            filetypes=[("PNG图片", "*.png"), ("JPG图片", "*.jpg"), ("所有文件", "*.*")]
        )

        if file_paths:
            success = self.detector.add_player_group(list(file_paths))
            if success:
                self.detector.load_player_templates()  # 重新加载缓存
                messagebox.showinfo("成功", f"人物图片导入成功！已自动生成左右方向图片")
                self.player_template_list_var.set(f"已加载模板: {self.detector.get_player_template_count()}")
            else:
                messagebox.showerror("失败", "导入人物图片失败")

    def open_player_dir(self):
        player_dir = os.path.join(self.base_dir, 'player')
        if not os.path.exists(player_dir):
            os.makedirs(player_dir)
        os.startfile(player_dir)

    def open_template_dir(self):
        template_dir = os.path.join(self.base_dir, 'monsters')
        if not os.path.exists(template_dir):
            os.makedirs(template_dir)
        os.startfile(template_dir)

    def add_monster_group(self):
        file_paths = filedialog.askopenfilenames(
            title="选择怪物图片组（可多选）",
            filetypes=[("PNG图片", "*.png"), ("JPG图片", "*.jpg"), ("所有文件", "*.*")]
        )

        if file_paths:
            group_name = simpledialog.askstring("输入怪物组名称", "请输入怪物组名称:")
            if group_name and group_name.strip():
                group_name = group_name.strip()
                success = self.detector.add_template_group(group_name, list(file_paths))
                if success:
                    messagebox.showinfo("成功", f"怪物组 [{group_name}] 导入成功！已自动生成左右方向图片")
                    self.template_list_var.set(f"已加载模板: {len(self.detector.templates)}")
                else:
                    messagebox.showerror("失败", "导入怪物组失败")
            else:
                messagebox.showwarning("警告", "请输入有效的怪物组名称")

    def _select_screen_region(self, target='hp'):
        """打开全屏透明遮罩，用鼠标框选区域，自动填写坐标"""
        # 隐藏主窗口
        self.root.withdraw()
        # 短暂延迟确保窗口隐藏
        self.root.after(200, lambda: self._start_region_select(target))

    def _start_region_select(self, target):
        """创建全屏透明窗口进行区域框选"""
        self._sel_overlay = tk.Toplevel()
        self._sel_overlay.attributes('-fullscreen', True)
        self._sel_overlay.attributes('-alpha', 0.3)
        self._sel_overlay.attributes('-topmost', True)
        self._sel_overlay.configure(bg='gray')
        self._sel_overlay.title(f"框选{target.upper()}区域 - 拖拽鼠标选择，ESC取消")

        # 用于绘制选择框的变量
        self._sel_start = None
        self._sel_rect_id = None
        self._sel_canvas = tk.Canvas(self._sel_overlay, bg='gray', highlightthickness=0)
        self._sel_canvas.pack(fill=tk.BOTH, expand=True)

        # 提示文字
        self._sel_canvas.create_text(
            self._sel_overlay.winfo_screenwidth() // 2,
            40,
            text=f"拖拽鼠标框选 {target.upper()} 条区域，松开完成，ESC取消",
            fill='white', font=('Arial', 16, 'bold')
        )

        self._sel_canvas.bind('<ButtonPress-1>', lambda e: self._on_sel_press(e))
        self._sel_canvas.bind('<B1-Motion>', lambda e: self._on_sel_drag(e))
        self._sel_canvas.bind('<ButtonRelease-1>', lambda e: self._on_sel_release(e, target))
        self._sel_overlay.bind('<Escape>', lambda e: self._cancel_sel())

    def _on_sel_press(self, event):
        self._sel_start = (event.x_root, event.y_root)
        if self._sel_rect_id:
            self._sel_canvas.delete(self._sel_rect_id)

    def _on_sel_drag(self, event):
        if self._sel_start is None:
            return
        if self._sel_rect_id:
            self._sel_canvas.delete(self._sel_rect_id)
        x1, y1 = self._sel_start
        x2, y2 = event.x_root, event.y_root
        # 转换为 canvas 本地坐标
        cx1 = min(x1, x2)
        cy1 = min(y1, y2)
        cx2 = max(x1, x2)
        cy2 = max(y1, y2)
        self._sel_rect_id = self._sel_canvas.create_rectangle(
            cx1, cy1, cx2, cy2,
            outline='lime', width=2, fill=''
        )

    def _on_sel_release(self, event, target):
        if self._sel_start is None:
            return
        x1, y1 = self._sel_start
        x2, y2 = event.x_root, event.y_root
        # 确保 x1 < x2, y1 < y2
        rx1, rx2 = sorted([x1, x2])
        ry1, ry2 = sorted([y1, y2])

        self._sel_overlay.destroy()
        self.root.deiconify()

        # 区域太小则忽略
        if rx2 - rx1 < 5 or ry2 - ry1 < 5:
            messagebox.showwarning("提示", "选择区域太小，请重新框选")
            return

        # 填写坐标
        if target == 'hp':
            self.hp_rx1_var.set(str(rx1))
            self.hp_ry1_var.set(str(ry1))
            self.hp_rx2_var.set(str(rx2))
            self.hp_ry2_var.set(str(ry2))
            print(f"[HP区域] 已设置: ({rx1},{ry1}) ~ ({rx2},{ry2})")
        elif target == 'mp':
            self.mp_rx1_var.set(str(rx1))
            self.mp_ry1_var.set(str(ry1))
            self.mp_rx2_var.set(str(rx2))
            self.mp_ry2_var.set(str(ry2))
            print(f"[MP区域] 已设置: ({rx1},{ry1}) ~ ({rx2},{ry2})")
        elif target == 'capture':
            self.capture_x_var.set(str(rx1))
            self.capture_y_var.set(str(ry1))
            self.capture_width_var.set(str(rx2 - rx1))
            self.capture_height_var.set(str(ry2 - ry1))
            self.use_capture_region_var.set(True)
            print(f"[截图区域] 已设置: ({rx1},{ry1}) {rx2-rx1}x{ry2-ry1}")
        elif target == 'screenshot':
            # 框选截图：截图该区域并保存为图片
            try:
                import cv2
                screen = self.detector.capture_screen((rx1, ry1, rx2, ry2))
                save_path = filedialog.asksaveasfilename(
                    title="保存框选截图",
                    defaultextension=".png",
                    initialfile=f"region_{rx1}_{ry1}_{rx2}_{ry2}.png",
                    filetypes=[("PNG图片", "*.png"), ("JPG图片", "*.jpg"), ("所有文件", "*.*")]
                )
                if save_path:
                    screen_rgb = cv2.cvtColor(screen, cv2.COLOR_BGR2RGB)
                    Image.fromarray(screen_rgb).save(save_path)
                    print(f"[框选截图] 已保存: {save_path}")
                    label = f"截图已保存到:\n{save_path}"
                else:
                    label = '已取消保存'
            except Exception as e:
                label = f"截图保存失败: {e}"
                print(f"[框选截图] 失败: {e}")
        else:
            label = '未知区域'

        if target == 'hp':
            label = 'HP区域已设置'
        elif target == 'mp':
            label = 'MP区域已设置'
        elif target == 'capture':
            label = '游戏截图区域已设置'
        messagebox.showinfo("成功", f"{label}")

    def _cancel_sel(self):
        if hasattr(self, '_sel_overlay') and self._sel_overlay:
            self._sel_overlay.destroy()
        self.root.deiconify()

    def test_hp_detection(self):
        """测试HP检测，显示截图和检测结果"""
        self.update_config()
        if self.hpmp_detector.hp_region is None:
            messagebox.showwarning("提示", "请先设置HP检测区域坐标")
            return
        hp = self.hpmp_detector.detect_hp()
        if hp is not None:
            print(f"[HP检测] HP: {hp:.1f}%")
            messagebox.showinfo("HP检测结果", f"HP: {hp:.1f}%")
        else:
            print("[HP检测] 检测失败")
            messagebox.showerror("HP检测失败", "无法检测HP，请检查区域设置")

    def test_mp_detection(self):
        """测试MP检测，显示截图和检测结果"""
        self.update_config()
        if self.hpmp_detector.mp_region is None:
            messagebox.showwarning("提示", "请先设置MP检测区域坐标")
            return
        mp = self.hpmp_detector.detect_mp()
        if mp is not None:
            print(f"[MP检测] MP: {mp:.1f}%")
            messagebox.showinfo("MP检测结果", f"MP: {mp:.1f}%")
        else:
            print("[MP检测] 检测失败")
            messagebox.showerror("MP检测失败", "无法检测MP，请检查区域设置")

    def calibrate_hpmp(self):
        """校准HP/MP颜色范围，分析当前区域的颜色分布"""
        self.update_config()
        results = []
        if self.hpmp_detector.hp_region:
            info = self.hpmp_detector.calibrate(self.hpmp_detector.hp_region, 'hp')
            if info:
                results.append(f"HP区域: {info['total_pixels']}像素, "
                               f"有色像素: {info['colored_pixels']}, "
                               f"占比: {info['ratio']}, "
                               f"估算: {info['estimated_percent']}%")
        if self.hpmp_detector.mp_region:
            info = self.hpmp_detector.calibrate(self.hpmp_detector.mp_region, 'mp')
            if info:
                results.append(f"MP区域: {info['total_pixels']}像素, "
                               f"有色像素: {info['colored_pixels']}, "
                               f"占比: {info['ratio']}, "
                               f"估算: {info['estimated_percent']}%")
        if results:
            msg = "\n".join(results)
            print(f"[校准] {msg}")
            messagebox.showinfo("校准结果", msg)
        else:
            messagebox.showwarning("提示", "请先设置HP/MP检测区域")

    def add_wall_template(self):
        """导入墙面模板图片（自动生成左右方向图片）"""
        file_path = filedialog.askopenfilename(
            title="选择墙面图片",
            filetypes=[("PNG图片", "*.png"), ("JPG图片", "*.jpg"), ("所有文件", "*.*")]
        )
        if file_path:
            success = self.detector.add_wall_template(file_path)
            if success:
                self.detector.load_wall_templates()  # 重新加载缓存
                self.wall_template_list_var.set(f"已加载模板: {self.detector.get_wall_template_count()}")
                messagebox.showinfo("成功", "墙面图片导入成功！")
            else:
                messagebox.showerror("失败", "墙面图片导入失败")

    def open_wall_dir(self):
        """打开墙面模板目录"""
        wall_dir = os.path.join(self.base_dir, 'wall')
        if not os.path.exists(wall_dir):
            os.makedirs(wall_dir)
        os.startfile(wall_dir)

    def add_throwpoint_template(self):
        """导入抛点模板图片（抛点无需左右翻转）"""
        file_path = filedialog.askopenfilename(
            title="选择抛点图片",
            filetypes=[("PNG图片", "*.png"), ("JPG图片", "*.jpg"), ("所有文件", "*.*")]
        )
        if file_path:
            success = self.detector.add_throwpoint_template(file_path)
            if success:
                self.detector.load_throwpoint_templates()  # 重新加载缓存
                self.tp_template_list_var.set(f"已加载模板: {self.detector.get_throwpoint_template_count()}")
                messagebox.showinfo("成功", "抛点图片导入成功！")
            else:
                messagebox.showerror("失败", "抛点图片导入失败")

    def open_throwpoint_dir(self):
        """打开抛点模板目录"""
        tp_dir = os.path.join(self.base_dir, 'throwpoint')
        if not os.path.exists(tp_dir):
            os.makedirs(tp_dir)
        os.startfile(tp_dir)

    def _mark_walls(self, screen, walls):
        """在截图上用褐色框标记墙面（BGR 褐色约为 (42,42,165)）"""
        import cv2
        if not walls:
            print("未检测到墙面")
            return
        brown = (42, 42, 165)  # BGR 褐色
        for wall in walls:
            x1, y1, x2, y2 = wall['bbox']
            cv2.rectangle(screen, (int(x1), int(y1)), (int(x2), int(y2)), brown, 2)
            label = f"Wall: {wall['confidence']:.2f}"
            cv2.putText(screen, label, (int(x1), int(y1) - 5),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, brown, 1)
        print(f"[墙面检测] 检测到 {len(walls)} 个墙面")
        return walls

    def _mark_throwpoint(self, screen, throwpoints):
        """在截图上用黄色框标记原地抛点（BGR 黄色约为 (0,255,255)）"""
        import cv2
        if not throwpoints:
            print("未检测到原地抛点")
            return
        yellow = (0, 255, 255)  # BGR 黄色
        for tp in throwpoints:
            x1, y1, x2, y2 = tp['bbox']
            cv2.rectangle(screen, (int(x1), int(y1)), (int(x2), int(y2)), yellow, 2)
            label = f"ThrowPoint: {tp['confidence']:.2f}"
            cv2.putText(screen, label, (int(x1), int(y1) - 5),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, yellow, 1)
        print(f"[抛点检测] 检测到 {len(throwpoints)} 个原地抛点")
        return throwpoints

    def run(self):
        self.template_list_var.set(f"已加载模板: {len(self.detector.templates)}")
        self.player_template_list_var.set(f"已加载模板: {self.detector.get_player_template_count()}")
        self.wall_template_list_var.set(f"已加载模板: {self.detector.get_wall_template_count()}")
        self.tp_template_list_var.set(f"已加载模板: {self.detector.get_throwpoint_template_count()}")
        self._setup_f5_hotkey()  # 注册 F5 全局快捷键
        self.root.mainloop()


if __name__ == '__main__':
    bot = MapleStoryBot()
    bot.run()

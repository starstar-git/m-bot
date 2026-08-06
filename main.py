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
            player_templates_dir=os.path.join(self.base_dir, 'player')
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
            'hp_potion_key': '1',
            'mp_potion_key': '2',
            'attack_interval': 0.4,
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
        self.jump_key_combobox = ttk.Combobox(key_frame, textvariable=self.jump_key_var, values=jump_keys, width=10)
        self.jump_key_combobox.grid(row=1, column=1)

        ttk.Label(key_frame, text="HP药水键:").grid(row=2, column=0, padx=5, pady=2)
        self.hp_potion_key_var = tk.StringVar(value=self.config['hp_potion_key'])
        ttk.Entry(key_frame, textvariable=self.hp_potion_key_var, width=5).grid(row=2, column=1)

        ttk.Label(key_frame, text="MP药水键:").grid(row=2, column=2, padx=5, pady=2)
        self.mp_potion_key_var = tk.StringVar(value=self.config['mp_potion_key'])
        ttk.Entry(key_frame, textvariable=self.mp_potion_key_var, width=5).grid(row=2, column=3)

        move_keys = ['arrow_left','arrow_right']
        ttk.Label(key_frame, text="左移键:").grid(row=3, column=0, padx=5, pady=2)
        self.move_left_var = tk.StringVar(value='arrow_left')
        self.move_left_combobox = ttk.Combobox(key_frame, textvariable=self.move_left_var, values=move_keys, width=10)
        self.move_left_combobox.grid(row=3, column=1)

        ttk.Label(key_frame, text="右移键:").grid(row=3, column=2, padx=5, pady=2)
        self.move_right_var = tk.StringVar(value='arrow_right')
        self.move_right_combobox = ttk.Combobox(key_frame, textvariable=self.move_right_var, values=move_keys, width=10)
        self.move_right_combobox.grid(row=3, column=3)

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
        # 重置共享检测状态
        with self._state_lock:
            self._state['player_pos'] = None
            self._state['player_valid'] = False
            self._state['lost_count'] = 0
            self._state['monsters'] = []
            self._state['has_monsters'] = False
            self._state['nearest'] = None
            self._state['predicted_pos'] = None
            self._state['detect_frame'] = 0
            self._state['ready'] = False
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.status_var.set("运行中...")

        # 启动检测线程（截图/识别）与命令线程（发移动/攻击/技能命令）
        self._detection_thread = threading.Thread(target=self._detection_worker, daemon=True)
        self._detection_thread.start()
        self.bot_thread = threading.Thread(target=self.bot_loop, daemon=True)
        self.bot_thread.start()

    def stop_bot(self):
        self.running = False
        self.kb_controller.release_held_key()  # 释放持续按住的移动键
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.status_var.set("已停止")
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

        # 询问是否保存带标记的截图
        save = messagebox.askyesno("测试检测结果", f"{summary}\n\n是否保存带标记的截图？")
        if not save:
            return

        save_path = filedialog.asksaveasfilename(
            title="保存标记检测结果的截图",
            defaultextension=".png",
            filetypes=[("PNG图片", "*.png"), ("JPG图片", "*.jpg"), ("所有文件", "*.*")]
        )

        if save_path:
            screen_rgb = cv2.cvtColor(screen, cv2.COLOR_BGR2RGB)
            from PIL import Image
            img = Image.fromarray(screen_rgb)
            img.save(save_path)
            print(f"截图已保存到: {save_path}")
            messagebox.showinfo("成功", f"截图已保存到:\n{save_path}")
        else:
            print("用户取消了保存")

    def test_detection(self):
        """测试检测：统一临时截图检测一次。

        无论 bot 是否启动，都调用 detect_all_in_one() 截图并检测一次，
        可保存带标记截图（玩家红框、怪物绿框、移动区域紫框）。
        """
        self.update_config()

        print("临时截图检测一次...")
        region = self._get_capture_region()
        result = self.detector.detect_all_in_one(
            threshold=self.config['threshold'],
            player_threshold=self.config['player_threshold'],
            region=region
        )
        self._mark_and_save(
            result['screen'],
            result['player_info'],
            result['monsters'] or []
        )

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

    def _detection_worker(self):
        """检测线程：持续截图并检测玩家/怪物，将结果写入共享状态。

        只做图像检测，不发送任何键盘命令；命令线程（bot_loop）负责发命令。
        一次截图同时检测玩家和怪物，避免重复截图，提高检测频率。
        """
        while self.running:
            try:
                region = self._get_capture_region()
                result = self.detector.detect_all_in_one(
                    threshold=self.config['threshold'],
                    player_threshold=self.config['player_threshold'],
                    region=region
                )

                player_info = result['player_info']
                monsters = result['monsters'] or []

                # 计算最近怪（在检测线程完成，减少命令线程负担）
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

                # 向量外推预测位置（供玩家丢失时命令线程使用）
                predicted_pos = self.detector.predict_player_pos()

                with self._state_lock:
                    self._state['player_pos'] = player_info['position'] if player_info else None
                    self._state['player_valid'] = player_valid
                    self._state['lost_count'] = lost_count
                    self._state['monsters'] = monsters
                    self._state['has_monsters'] = len(monsters) > 0
                    self._state['nearest'] = nearest
                    self._state['predicted_pos'] = predicted_pos
                    self._state['detect_frame'] += 1
                    self._state['ready'] = True

                # 更新 GUI 怪物计数（检测线程同步）
                self._update_gui_safe(self.monster_count_var, f"检测到怪物: {len(monsters)}")

                # 控制检测频率
                time.sleep(self.config['detection_interval'])

            except Exception as e:
                print(f"[检测线程] 错误: {e}")
                traceback.print_exc()
                time.sleep(1)

    def bot_loop(self):
        while self.running:
            try:
                # === 原地攻击模式：跳过所有检测和移动，只按频率攻击 ===
                if self.stationary_attack_var.get():
                    self.kb_controller.release_held_key()
                    self.kb_controller.press_key(self.config['attack_key'], 0.05)
                    self.attack_strategy.attack_count += 1
                    # 原地模式根据开关决定是否释放技能
                    if self.stationary_use_skill_var.get():
                        self.attack_strategy.try_use_skills()
                    # 原地模式仍检测HP/MP
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
                    self._update_gui_safe(self.attack_count_var,
                        f"攻击次数: {self.attack_strategy.get_attack_count()}")
                    self._update_gui_safe(self.status_var, "原地攻击中...")
                    time.sleep(self.config['attack_interval'])
                    continue

                attack_distance = self.config['attack_distance']
                attack_distance_y = self.config['attack_distance_y']
                move_keys = {
                    'left': self.config['move_left'],
                    'right': self.config['move_right']
                }

                # === 1. 读取检测线程的最新结果（不再自己截图/检测） ===
                state = self._read_state()
                player_pos = state['player_pos']
                player_valid = state['player_valid']
                lost_count = state['lost_count']
                nearest = state['nearest']
                predicted_pos = state['predicted_pos']
                detect_frame = state['detect_frame']

                # 未产生第一帧结果时先等待检测线程
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

                        if lost_count == 1:
                            # 首次丢失：向丢失前标记的方向移动寻找
                            self.kb_controller.release_held_key()
                            self.kb_controller.hold_key_continuous(move_keys[self._patrol_direction])
                            print(f"[玩家丢失] 开始向 {self._patrol_direction} 移动寻找")
                        elif lost_count % 10 == 0 and lost_count > 0:
                            # 每10次仍未找到：反向巡逻，扩大寻找范围
                            self._patrol_direction = 'right' if self._patrol_direction == 'left' else 'left'
                            self.kb_controller.release_held_key()
                            self.kb_controller.hold_key_continuous(move_keys[self._patrol_direction])
                            print(f"[玩家丢失] 第{lost_count}次未找到，反向巡逻: {self._patrol_direction}")
                        else:
                            # 继续沿当前方向寻找
                            self.kb_controller.hold_key_continuous(move_keys[self._patrol_direction])
                else:
                    # 首次未检测到玩家且无历史记录
                    player_pos = (0, 0)
                    self._last_player_pos = player_pos
                    self._update_gui_safe(self.player_pos_var, f"玩家位置: 丢失({lost_count})")
                    self.kb_controller.hold_key_continuous(move_keys[self._patrol_direction])
                    print(f"[玩家丢失] 首次未检测，向 {self._patrol_direction} 移动")

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
                    # 玩家丢失且此前在打怪：用预测位置继续打怪
                    if lost_count > 0:
                        print(f"[玩家丢失-继续打怪] 按预测位置继续攻击 ({lost_count})")
                        self._update_gui_safe(self.player_pos_var,
                            f"玩家位置: 丢失({lost_count})-继续打怪")

                    # 防御：无玩家位置则跳过本帧攻击决策，避免解包 None 崩溃
                    if player_pos is None:
                        self._was_attacking = False
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
                            # 优先保证在移动区域内：若追怪方向会导致跑出区域，则放弃追怪，转向回区域
                            self._was_attacking = False
                            # 判断用位置：优先用预测位置，降低延迟影响
                            px_judge = predicted_pos[0] if predicted_pos is not None else px

                            if mx > px:
                                # 怪物在右侧：只有未到右边界才追，否则转向回区域
                                if px_judge >= region_right:
                                    self.kb_controller.hold_key_continuous(move_keys['left'])
                                else:
                                    self.kb_controller.hold_key_continuous(move_keys['right'])
                            elif mx < px:
                                # 怪物在左侧：只有未到左边界才追，否则转向回区域
                                if px_judge <= region_left:
                                    self.kb_controller.hold_key_continuous(move_keys['right'])
                                else:
                                    self.kb_controller.hold_key_continuous(move_keys['left'])
                    else:
                        # === 情况3：无怪物 ===
                        self._was_attacking = False
                        if near_boundary and judge_x is not None:
                            # 人物在区域外：转向回区域（朝区域中心方向）
                            back_dir = 'right' if judge_x < region_left else 'left'
                            self._patrol_direction = back_dir
                            self.kb_controller.hold_key_continuous(move_keys[back_dir])
                            print(f"[回区域] 人物在区域外(judge_x={int(judge_x)})，转向: {back_dir}")
                        else:
                            # 人物在区域内：左右巡逻
                            if self._patrol_direction == 'left':
                                self.kb_controller.hold_key_continuous(move_keys['left'])
                            else:
                                self.kb_controller.hold_key_continuous(move_keys['right'])

                # === 5. 更新攻击计数 ===
                self._update_gui_safe(self.attack_count_var,
                    f"攻击次数: {self.attack_strategy.get_attack_count()}")

                # === 命令线程节奏：使用短间隔快速响应检测结果 ===
                # 检测线程负责截图/匹配（受 detection_interval 控制），
                # 命令线程只发命令，短轮询即可即时响应最新检测状态。
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
        self.template_list_var.set(f"已加载模板: {len(self.detector.templates)}")
        self.player_template_list_var.set(f"已加载模板: {self.detector.get_player_template_count()}")

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

        label = 'HP' if target == 'hp' else ('MP' if target == 'mp' else '游戏截图')
        messagebox.showinfo("成功", f"{label}区域已设置")

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

    def run(self):
        self.template_list_var.set(f"已加载模板: {len(self.detector.templates)}")
        self.player_template_list_var.set(f"已加载模板: {self.detector.get_player_template_count()}")
        self._setup_f5_hotkey()  # 注册 F5 全局快捷键
        self.root.mainloop()


if __name__ == '__main__':
    bot = MapleStoryBot()
    bot.run()

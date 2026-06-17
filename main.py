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

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'libs'))

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from PIL import Image, ImageTk

from monster_detector import MonsterDetector
from keyboard_controller import KeyboardController, AttackStrategy
from hpmp_detector import HPMPDetector


class MapleStoryBot:
    """自动化打怪脚本主程序"""

    def __init__(self):
        self.running = False
        self.detector = MonsterDetector()
        self.kb_controller = KeyboardController()
        self.attack_strategy = AttackStrategy(self.kb_controller)
        self.hpmp_detector = HPMPDetector()

        self.config = {
            'attack_key': 'j',
            'skill_key': 'k',
            'skill1_key': 'l',
            'jump_key': 'space',
            'move_left': 'a',
            'move_right': 'd',
            'hp_potion_key': '1',
            'mp_potion_key': '2',
            'attack_interval': 0.3,
            'threshold': 0.7,
            'player_threshold': 0.7,
            'attack_distance': 400,
            'attack_distance_y': 100,
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
            'detection_interval': 0.5
        }

        self.setup_gui()

    def setup_gui(self):
        """创建GUI界面"""
        self.root = tk.Tk()
        self.root.title("自动化打怪脚本")
        self.root.geometry("900x600")
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
        ttk.Button(row2, text="测试玩家", command=self.test_move_mouse).pack(side=tk.LEFT, padx=5)
        ttk.Button(row2, text="测试怪物", command=self.test_move_to_monster).pack(side=tk.LEFT, padx=5)

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

        ttk.Label(key_frame, text="跳跃键:").grid(row=1, column=0, padx=5, pady=2)
        self.jump_key_var = tk.StringVar(value=self.config['jump_key'])
        ttk.Entry(key_frame, textvariable=self.jump_key_var, width=5).grid(row=1, column=1)

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

        ttk.Label(param_frame, text="攻击间隔(秒):").grid(row=1, column=0, padx=5, pady=2)
        self.attack_interval_var = tk.StringVar(value=str(self.config['attack_interval']))
        ttk.Entry(param_frame, textvariable=self.attack_interval_var, width=8).grid(row=1, column=1)

        ttk.Label(param_frame, text="MP药水百分比:").grid(row=1, column=2, padx=5, pady=2)
        self.mp_potion_percent_var = tk.StringVar(value=str(self.config['mp_potion_percent']))
        ttk.Entry(param_frame, textvariable=self.mp_potion_percent_var, width=8).grid(row=1, column=3)

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
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.status_var.set("运行中...")

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
    
    def test_move_mouse(self):
        """测试：截图并标记玩家位置，保存到指定位置"""
        self.update_config()
        
        print("正在截图并检测玩家...")
        
        region = self._get_capture_region()
        screen = self.detector.capture_screen(region)
        player_info = self.detector.detect_player_by_name(
            "",
            threshold=self.config['player_threshold'],
            region=region
        )
        
        if player_info:
            print(f"检测到玩家位置")
            
            import cv2
            
            bbox = player_info.get('bbox')
            if bbox:
                x1, y1, x2, y2 = bbox
                cv2.rectangle(screen, (int(x1), int(y1)), (int(x2), int(y2)), (0, 0, 255), 2)
                
                label = f"Player: {player_info['template']} ({player_info['confidence']:.2f})"
                cv2.putText(screen, label, (int(x1), int(y1) - 5), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
            else:
                # 如果没有bbox，使用位置画一个圆点标记
                x, y = player_info['position']
                cv2.circle(screen, (int(x), int(y)), 20, (0, 0, 255), 2)
                label = f"Player: {player_info['template']} ({player_info['confidence']:.2f})"
                cv2.putText(screen, label, (int(x) - 50, int(y) - 25), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
            
            save_path = filedialog.asksaveasfilename(
                title="保存标记玩家的截图",
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
        else:
            print("未检测到玩家，请检查：")
            print(f"  - 玩家模板是否已导入到 player 目录")
            print(f"  - 识别阈值是否设置过低（当前: {self.config['player_threshold']}）")
            print(f"  - 游戏窗口是否在屏幕可见范围内")

    def test_move_to_monster(self):
        """测试：截图并标记怪物位置，保存到指定位置"""
        self.update_config()
        
        print("正在截图并检测怪物...")
        
        region = self._get_capture_region()
        screen = self.detector.capture_screen(region)
        monsters = self.detector.detect_monsters(threshold=self.config['threshold'], region=region)
        
        if monsters:
            print(f"检测到 {len(monsters)} 个怪物")
            
            import cv2
            import numpy as np
            
            for monster in monsters:
                x1, y1, x2, y2 = monster['bbox']
                cv2.rectangle(screen, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 0), 2)
                
                label = f"{monster['name']}: {monster['confidence']:.2f}"
                cv2.putText(screen, label, (int(x1), int(y1) - 5), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
            
            save_path = filedialog.asksaveasfilename(
                title="保存标记怪物的截图",
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
        else:
            print("没有检测到怪物，请检查：")
            print(f"  - 怪物模板是否已导入到 monsters 目录")
            print(f"  - 识别阈值是否设置过低（当前: {self.config['threshold']}）")
            print(f"  - 游戏窗口是否在屏幕可见范围内")
            print(f"  - 当前已加载怪物模板数量: {len(self.detector.templates)}")

    def _update_gui_safe(self, var, value):
        """线程安全地更新GUI变量"""
        try:
            self.root.after(0, lambda: var.set(value))
        except Exception:
            pass

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

                region = self._get_capture_region()
                attack_distance = self.config['attack_distance']
                attack_distance_y = self.config['attack_distance_y']
                move_keys = {
                    'left': self.config['move_left'],
                    'right': self.config['move_right']
                }

                # === 1. 检测玩家位置 ===
                player_info = self.detector.detect_player_by_name(
                    "",
                    threshold=self.config['player_threshold'],
                    region=region
                )
                # 使用 detector 内部的丢失计数（模板匹配失败时自动递增，检测到时自动清零）
                lost_count = self.detector.player_lost_count

                if player_info:
                    player_pos = player_info['position']
                    self._last_player_pos = player_pos
                    self._update_gui_safe(self.player_pos_var,
                        f"玩家位置: ({int(player_pos[0])}, {int(player_pos[1])})")
                elif self._last_player_pos is not None:
                    player_pos = self._last_player_pos
                    self._update_gui_safe(self.player_pos_var, f"玩家位置: 丢失({lost_count})")

                    if lost_count % 10 == 0:
                        # 每10次根据预测位置判断方向：在截图左半边则向右，右半边则向左
                        capture_width = self.config['capture_width'] if self.config['use_capture_region'] else 1024
                        predicted_x = self._last_player_pos[0]
                        screen_mid = capture_width / 2

                        if predicted_x < screen_mid:
                            new_dir = 'right'
                        else:
                            new_dir = 'left'

                        self._patrol_direction = new_dir
                        self.kb_controller.release_held_key()
                        self.kb_controller.hold_key_continuous(move_keys[self._patrol_direction])
                        print(f"[玩家丢失] 第{lost_count}次，预测x={int(predicted_x)}，宽={capture_width}，中点={int(screen_mid)}，方向: {self._patrol_direction}")
                    else:
                        self.kb_controller.hold_key_continuous(move_keys[self._patrol_direction])
                        if lost_count == 1:
                            print(f"[玩家丢失] 开始向 {self._patrol_direction} 移动寻找")
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

                # === 2. 边界检测（玩家在游戏框边缘100像素内时强制转向） ===
                if lost_count == 0:
                    player_x = player_pos[0]
                    capture_width = self.config['capture_width'] if self.config['use_capture_region'] else 1024
                    near_boundary = False

                    if player_x < 100:
                        self._patrol_direction = 'right'
                        near_boundary = True
                    elif player_x > capture_width - 100:
                        self._patrol_direction = 'left'
                        near_boundary = True

                    if near_boundary:
                        self.kb_controller.release_held_key()
                        self.kb_controller.hold_key_continuous(move_keys[self._patrol_direction])
                        print(f"[边界] 玩家x={int(player_x)}，宽={capture_width}，转向: {self._patrol_direction}")
                    else:
                        # === 3. 检测怪物 ===
                        monsters = self.detector.detect_monsters(
                            threshold=self.config['threshold'], region=region
                        )
                        self._update_gui_safe(self.monster_count_var, f"检测到怪物: {len(monsters)}")

                        # === 4. 攻击/移动决策 ===
                        nearest = None
                        if monsters:
                            nearest = self.detector.find_nearest_monster(
                                player_pos, monsters, y_tolerance=attack_distance_y
                            )

                        if nearest:
                            px, py_pos = player_pos
                            mx, my = nearest['position']
                            x_distance = abs(mx - px)
                            y_distance = abs(my - py_pos)

                            if x_distance < attack_distance and y_distance <= attack_distance_y:
                                self.kb_controller.release_held_key()
                                self.kb_controller.turn_direction(
                                    player_pos, nearest['position'], move_keys
                                )
                                self.attack_strategy.execute_attack(x_distance)
                            else:
                                if mx > px:
                                    self.kb_controller.hold_key_continuous(move_keys['right'])
                                elif mx < px:
                                    self.kb_controller.hold_key_continuous(move_keys['left'])
                        else:
                            # 无怪物：巡逻移动
                            if self._patrol_direction == 'left':
                                self.kb_controller.hold_key_continuous(move_keys['left'])
                            else:
                                self.kb_controller.hold_key_continuous(move_keys['right'])

                # === 5. 更新攻击计数 ===
                self._update_gui_safe(self.attack_count_var,
                    f"攻击次数: {self.attack_strategy.get_attack_count()}")

                time.sleep(self.config['detection_interval'])

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
        """尝试检测游戏窗口"""
        try:
            hwnd = ctypes.windll.user32.FindWindowW(None, "MapleStory")
            if hwnd:
                rect = ctypes.wintypes.RECT()
                ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
                self.capture_x_var.set(str(rect.left))
                self.capture_y_var.set(str(rect.top))
                self.capture_width_var.set(str(rect.right - rect.left))
                self.capture_height_var.set(str(rect.bottom - rect.top))
                self.use_capture_region_var.set(True)
                messagebox.showinfo("成功", f"已检测到游戏窗口:\n位置: ({rect.left}, {rect.top})\n大小: {rect.right-rect.left} x {rect.bottom-rect.top}")
            else:
                messagebox.showwarning("提示", "未找到名为'MapleStory'的窗口，请手动设置区域")
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
        player_dir = os.path.join(os.path.dirname(__file__), 'player')
        if not os.path.exists(player_dir):
            os.makedirs(player_dir)
        os.startfile(player_dir)

    def open_template_dir(self):
        template_dir = os.path.join(os.path.dirname(__file__), 'monsters')
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

# -*- coding: utf-8 -*-
# 冒险岛自动化打怪脚本
# HP/MP 检测模块 - 通过颜色比例检测血量/蓝量

import cv2
import numpy as np
from PIL import ImageGrab


class HPMPDetector:
    """HP/MP 检测器 - 通过截取血条/蓝条区域，检测颜色像素占比来计算百分比"""

    def __init__(self):
        # HP 条检测区域 (x1, y1, x2, y2) 屏幕坐标
        self.hp_region = None
        # MP 条检测区域 (x1, y1, x2, y2) 屏幕坐标
        self.mp_region = None

        # HSV 颜色范围（可调）
        # HP: 红色系 (冒险岛HP条通常是红色)
        self.hp_hsv_ranges = [
            (np.array([0, 50, 50]), np.array([10, 255, 255])),    # 红色低段
            (np.array([170, 50, 50]), np.array([180, 255, 255])),  # 红色高段
        ]
        # MP: 蓝色系 (冒险岛MP条通常是蓝色)
        self.mp_hsv_ranges = [
            (np.array([90, 50, 50]), np.array([130, 255, 255])),  # 蓝色
        ]

        # 最小有效像素占比（排除背景噪声）
        self.min_valid_ratio = 0.02

        # 上次检测结果（用于容错）
        self.last_hp_percent = 100.0
        self.last_mp_percent = 100.0

    def set_hp_region(self, region):
        """设置HP条检测区域 (x1, y1, x2, y2)"""
        self.hp_region = region

    def set_mp_region(self, region):
        """设置MP条检测区域 (x1, y1, x2, y2)"""
        self.mp_region = region

    def _capture_region(self, region):
        """截取屏幕区域，返回 BGR numpy 数组"""
        if region is None:
            return None
        try:
            img = ImageGrab.grab(bbox=region)
            return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        except Exception as e:
            print(f"[HP/MP] 截图失败: {e}")
            return None

    def _count_colored_pixels(self, img_hsv, color_ranges):
        """统计匹配颜色范围的像素数量"""
        mask = np.zeros(img_hsv.shape[:2], dtype=np.uint8)
        for lower, upper in color_ranges:
            mask |= cv2.inRange(img_hsv, lower, upper)
        return cv2.countNonZero(mask)

    def detect_hp(self):
        """检测HP百分比，返回 0-100 的浮点数，检测失败返回 None"""
        if self.hp_region is None:
            return None

        img = self._capture_region(self.hp_region)
        if img is None:
            return None

        img_hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        total_pixels = img.shape[0] * img.shape[1]

        colored_pixels = self._count_colored_pixels(img_hsv, self.hp_hsv_ranges)
        ratio = colored_pixels / total_pixels if total_pixels > 0 else 0

        # 排除噪声
        if ratio < self.min_valid_ratio:
            percent = 0.0
        else:
            # 线性映射：通常满血时有色像素占比约 60-90%，映射到 100%
            # 使用校准后的最大值，默认 0.85
            max_ratio = 0.85
            percent = min(ratio / max_ratio * 100, 100.0)

        self.last_hp_percent = percent
        return percent

    def detect_mp(self):
        """检测MP百分比，返回 0-100 的浮点数，检测失败返回 None"""
        if self.mp_region is None:
            return None

        img = self._capture_region(self.mp_region)
        if img is None:
            return None

        img_hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        total_pixels = img.shape[0] * img.shape[1]

        colored_pixels = self._count_colored_pixels(img_hsv, self.mp_hsv_ranges)
        ratio = colored_pixels / total_pixels if total_pixels > 0 else 0

        if ratio < self.min_valid_ratio:
            percent = 0.0
        else:
            max_ratio = 0.85
            percent = min(ratio / max_ratio * 100, 100.0)

        self.last_mp_percent = percent
        return percent

    def detect_all(self):
        """同时检测 HP 和 MP，返回 (hp_percent, mp_percent)"""
        hp = self.detect_hp()
        mp = self.detect_mp()
        return hp, mp

    def calibrate(self, region, bar_type='hp'):
        """校准：截取区域并分析当前颜色分布，自动调整颜色范围"""
        img = self._capture_region(region)
        if img is None:
            return None

        img_hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        total_pixels = img.shape[0] * img.shape[1]

        if bar_type == 'hp':
            # 分析红色像素分布
            ranges_to_try = [
                (np.array([0, 30, 30]), np.array([15, 255, 255])),
                (np.array([165, 30, 30]), np.array([180, 255, 255])),
            ]
        else:
            # 分析蓝色像素分布
            ranges_to_try = [
                (np.array([80, 30, 30]), np.array([140, 255, 255])),
            ]

        colored = self._count_colored_pixels(img_hsv, ranges_to_try)
        ratio = colored / total_pixels if total_pixels > 0 else 0

        info = {
            'total_pixels': total_pixels,
            'colored_pixels': colored,
            'ratio': round(ratio, 4),
            'estimated_percent': round(min(ratio / 0.85 * 100, 100), 1),
            'region': region,
            'bar_type': bar_type
        }
        return info

    def get_preview_image(self, region, bar_type='hp'):
        """获取预览图：截图 + 标记检测到的颜色区域"""
        img = self._capture_region(region)
        if img is None:
            return None

        img_hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

        if bar_type == 'hp':
            ranges = self.hp_hsv_ranges
            overlay_color = (0, 0, 255)  # 红色
        else:
            ranges = self.mp_hsv_ranges
            overlay_color = (255, 0, 0)  # 蓝色

        mask = np.zeros(img_hsv.shape[:2], dtype=np.uint8)
        for lower, upper in ranges:
            mask |= cv2.inRange(img_hsv, lower, upper)

        # 创建颜色叠加层
        colored_overlay = np.zeros_like(img)
        colored_overlay[mask > 0] = overlay_color

        # 混合原图和颜色标记
        result = cv2.addWeighted(img, 0.7, colored_overlay, 0.3, 0)

        # 添加文字信息
        colored_pixels = cv2.countNonZero(mask)
        total = img.shape[0] * img.shape[1]
        ratio = colored_pixels / total if total > 0 else 0
        percent = min(ratio / 0.85 * 100, 100)

        cv2.putText(result, f"{percent:.1f}%", (5, 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

        return result


if __name__ == '__main__':
    # 测试
    detector = HPMPDetector()
    print("HP/MP 检测器初始化完成")
    print("请通过 GUI 设置检测区域后使用")

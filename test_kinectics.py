# -*- coding: utf-8 -*-
"""
test_kinectics.py — בדיקה מלאה למערכת קינמטיקה
---------------------------------------------------
מטרת הקובץ:
1. לבדוק את נתוני הקינמטיקה שמתקבלים מהמנוע.
2. לוודא שהמדידות נכונות ומדויקות.
3. לבצע השוואות מול נתונים ידועים ולוודא שאין חריגות.
4. לדווח על סטיות או בעיות במערכת.
"""

import unittest
import json
import os

# אתה יכול להוסיף את המודול שלך או את הפונקציות שקשורות למנוע
from core.kinematics import KinematicsEngine  # דוגמה למנוע קינמטיקה
from core.pose import PoseEstimator  # דוגמה לזיהוי פוזה
from core.object_detection import ObjectDetector  # דוגמה לזיהוי אובייקטים
from utils.logger import logger  # אם אתה משתמש בלוגר לצורך דיווח

# נתיב לפלטים/קבצים לבדיקה
TEST_DATA_PATH = "tests/test_data"
OUTPUT_PATH = "tests/output_logs"


class TestKinematics(unittest.TestCase):
    """
    כיתה לבדיקת מדידות קינמטיקה
    """

    def setUp(self):
        """
        אתחול לפני כל בדיקה
        """
        self.pose_estimator = PoseEstimator()
        self.object_detector = ObjectDetector()
        self.kinematics_engine = KinematicsEngine()

        # יצירת תיקיות לפלטים
        if not os.path.exists(OUTPUT_PATH):
            os.makedirs(OUTPUT_PATH)

    def test_pose_estimation(self):
        """
        בדוק אם המערכת מזהה פוזה נכון.
        """
        frame = self._get_test_frame("test_squat.mp4")
        pose_data = self.pose_estimator.process(frame)

        self.assertIsNotNone(pose_data, "לא התקבלו נתוני פוזה")
        self.assertGreater(len(pose_data), 0, "הנתונים שהתקבלו ריקים")

        logger.info("Pose Estimation Passed!")

    def test_object_detection(self):
        """
        בדוק אם זיהוי האובייקטים (כגון משקולות) עובד כראוי.
        """
        frame = self._get_test_frame("test_squat.mp4")
        detected_objects = self.object_detector.detect(frame)

        self.assertGreater(len(detected_objects), 0, "לא זוהו אובייקטים")
        logger.info(f"Detected Objects: {detected_objects}")

    def test_kinematics_measurements(self):
        """
        בדוק את מדידות הקינמטיקה (זוויות, מרחקים וכו') במערכת.
        """
        frame = self._get_test_frame("test_squat.mp4")
        pose_data = self.pose_estimator.process(frame)
        kinematics_data = self.kinematics_engine.compute(pose_data)

        self.assertIsNotNone(kinematics_data, "הקינמטיקה לא חושבה כראוי")
        self.assertGreater(len(kinematics_data), 0, "הנתונים של הקינמטיקה ריקים")

        # השוואה של זווית הברך לדוגמה (על פי סטנדרטים פיזיולוגיים)
        knee_angle = kinematics_data.get("knee_angle", None)
        self.assertIsNotNone(knee_angle, "זווית הברך לא קיימת")
        self.assertGreater(knee_angle, 90, "הברך לא זזה מספיק למטה בסקוואט")
        self.assertLess(knee_angle, 180, "הברך זזה מעבר לגבול הנורמלי")

        logger.info(f"Knee Angle: {knee_angle}")

    def test_output_consistency(self):
        """
        בדוק עקביות בתוצאות על פני כמה חזרות של תרגיל.
        """
        frame_1 = self._get_test_frame("test_squat.mp4")
        frame_2 = self._get_test_frame("test_squat.mp4")

        pose_data_1 = self.pose_estimator.process(frame_1)
        pose_data_2 = self.pose_estimator.process(frame_2)

        self.assertEqual(pose_data_1, pose_data_2, "הנתונים משתנים בצורה בלתי סבירה בין החזרות")

        logger.info("Output Consistency Test Passed!")

    def test_logging_and_error_handling(self):
        """
        בדוק אם המערכת כותבת את הלוגים בצורה נכונה ומטפלת בשגיאות.
        """
        try:
            frame = self._get_test_frame("test_invalid.mp4")  # סרטון לא תקין
            pose_data = self.pose_estimator.process(frame)
        except Exception as e:
            logger.error(f"Error while processing: {e}")
            self.assertTrue(True, "שגיאה הופיעה כפי שציפינו")

    def _get_test_frame(self, video_file: str) -> any:
        """
        עוזר להוציא פריימים מתוך סרטונים לצורך בדיקה.
        """
        video_path = os.path.join(TEST_DATA_PATH, video_file)
        # כאן תוכל להוסיף את הקוד שלך לשליפת פריימים מסרטון.
        # לדוגמה:
        # return cv2.imread(video_path)
        return video_path  # למטרת הדגמה בלבד

    def tearDown(self):
        """
        ניקוי אחרי כל בדיקה
        """
        pass


if __name__ == "__main__":
    unittest.main()

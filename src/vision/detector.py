# import cv2
# import time
# import numpy as np
# from ultralytics import YOLO
# from config.settings import DETECTION_MODEL_PATH, HAZARD_CLASSES, VEHICLE_CLASSES

# class SpiritVision:
#     def __init__(self):
#         # Load YOLO-seg (Instance Segmentation) or RT-DETR for superior performance
#         try:
#             self.model = YOLO(DETECTION_MODEL_PATH) 
#         except:
#             print("Local ONNX not found, loading YOLOv8n-seg for setup. Export to ONNX later!")
#             ## for pothholes use this
#             # self.model = YOLO('yolov8n-seg.pt') 
#             self.model = YOLO("models/yolo11n.onnx", task='detect')
            
#         self.prev_vehicle_boxes = {}
#         self.frame_count = 0

#     def process_frame(self, frame):
#         """Runs inference and calculates dynamic hazards."""
#         self.frame_count += 1
#         results = self.model(frame, conf=0.4, imgsz=320, verbose=False)[0]
        
#         annotations = []
#         urgent_vehicles = []

#         # Extract masks and boxes
#         if results.masks is not None:
#             masks = results.masks.data.cpu().numpy()
#             boxes = results.boxes.data.cpu().numpy()
            
#             for box, mask in zip(boxes, masks):
#                 x1, y1, x2, y2, conf, cls_id = box
#                 class_name = self.model.names[int(cls_id)]
                
#                 # 1. Check for fast approaching vehicles (Time-to-Collision logic)
#                 if class_name in VEHICLE_CLASSES:
#                     vehicle_id = f"{class_name}_{int(x1//50)}"
#                     current_area = (x2 - x1) * (y2 - y1)
                    
#                     if vehicle_id in self.prev_vehicle_boxes:
#                         prev_area = self.prev_vehicle_boxes[vehicle_id]
#                         if prev_area > 0:
#                             expansion_rate = current_area / prev_area
#                             if expansion_rate > 1.5: # Vehicle growing 50% in one frame = FAST
#                                 urgent_vehicles.append(f"Warning! Fast {class_name} approaching!")

#                     self.prev_vehicle_boxes[vehicle_id] = current_area

#                 # 2. Check for static hazards (using segmentation masks)
#                 elif class_name in HAZARD_CLASSES:
#                     # Reshape mask to image dimensions
#                     mask_resized = cv2.resize(mask, (frame.shape[1], frame.shape[0]))
#                     binary_mask = (mask_resized > 0.5).astype(np.uint8)
#                     hazard_area_px = np.sum(binary_mask)
                    
#                     if hazard_area_px > 5000: # If hazard takes up significant screen space
#                         annotations.append(f"Critical {class_name} directly ahead!")

#         # Draw visual annotations (for debugging/remote viewing)
#         annotated_frame = results.plot()
        
#         return annotated_frame, annotations, urgent_vehicles




# import cv2
# import time
# import numpy as np
# from ultralytics import YOLO
# from config.settings import DETECTION_MODEL_PATH, HAZARD_CLASSES, VEHICLE_CLASSES

# class SpiritVision:
#     def __init__(self):
#         # Load YOLO-seg (Instance Segmentation) or RT-DETR for superior performance
#         try:
#             self.model = YOLO(DETECTION_MODEL_PATH) 
#         except:
#             print("Local ONNX not found, loading YOLOv8n-seg for setup. Export to ONNX later!")
#             ## for pothholes use this
#             # self.model = YOLO('yolov8n-seg.pt') 
#             self.model = YOLO("models/yolo11n.onnx", task='detect')
            
#         self.prev_vehicle_boxes = {}
#         self.frame_count = 0

#     def process_frame(self, frame):
#         """
#         Runs inference and calculates dynamic hazards.

#         Returns (annotated_frame, hazard_class_names, urgent_vehicle_class_names)
#         — BARE class names (e.g. "pothole", "car"), one entry per detected
#         instance meeting the threshold, not pre-built sentences. This is
#         deliberate: fusion_engine.py (safety announcements) and
#         build_environment_summary() (AI context) both count occurrences
#         per class to say things like "2 potholes and 1 tree" — that only
#         works cleanly if this returns class names, not full sentences with
#         per-detection wording baked in. Natural-language phrasing/urgency
#         wording lives centrally in fusion_engine.py now, not here.
#         """
#         self.frame_count += 1
#         results = self.model(frame, conf=0.4, imgsz=320, verbose=False)[0]
        
#         annotations = []
#         urgent_vehicles = []

#         # Extract masks and boxes
#         if results.masks is not None:
#             masks = results.masks.data.cpu().numpy()
#             boxes = results.boxes.data.cpu().numpy()
            
#             for box, mask in zip(boxes, masks):
#                 x1, y1, x2, y2, conf, cls_id = box
#                 class_name = self.model.names[int(cls_id)]
                
#                 # 1. Check for fast approaching vehicles (Time-to-Collision logic)
#                 if class_name in VEHICLE_CLASSES:
#                     vehicle_id = f"{class_name}_{int(x1//50)}"
#                     current_area = (x2 - x1) * (y2 - y1)
                    
#                     if vehicle_id in self.prev_vehicle_boxes:
#                         prev_area = self.prev_vehicle_boxes[vehicle_id]
#                         if prev_area > 0:
#                             expansion_rate = current_area / prev_area
#                             if expansion_rate > 1.5: # Vehicle growing 50% in one frame = FAST
#                                 urgent_vehicles.append(class_name)

#                     self.prev_vehicle_boxes[vehicle_id] = current_area

#                 # 2. Check for static hazards (using segmentation masks)
#                 elif class_name in HAZARD_CLASSES:
#                     # Reshape mask to image dimensions
#                     mask_resized = cv2.resize(mask, (frame.shape[1], frame.shape[0]))
#                     binary_mask = (mask_resized > 0.5).astype(np.uint8)
#                     hazard_area_px = np.sum(binary_mask)
                    
#                     if hazard_area_px > 5000: # If hazard takes up significant screen space
#                         annotations.append(class_name)

#         # Draw visual annotations (for debugging/remote viewing)
#         annotated_frame = results.plot()
        
#         return annotated_frame, annotations, urgent_vehicles






import cv2
import time
import warnings
import numpy as np
from ultralytics import YOLO
from config.settings import DETECTION_MODEL_PATH, HAZARD_CLASSES, VEHICLE_CLASSES


class SpiritVision:
    def __init__(self):
        loaded = False
        try:
            self.model = YOLO(DETECTION_MODEL_PATH)
            print(f"INFO: Loaded model from {DETECTION_MODEL_PATH}")
            loaded = True
        except Exception as e:
            print(f"WARNING: Could not load {DETECTION_MODEL_PATH}: {e}")
        
        if not loaded:
            try:
                self.model = YOLO("models/yolo11n.onnx", task='detect')
                print("INFO: Loaded fallback model models/yolo11n.onnx")
                loaded = True
            except Exception as e:
                print(f"WARNING: Could not load yolo11n.onnx: {e}")
        
        if not loaded:
            print("INFO: Downloading yolov8n-seg.pt as last resort...")
            self.model = YOLO('yolov8n-seg.pt')
            print("INFO: Loaded yolov8n-seg.pt")
        
        all_classes = list(self.model.names.values())
        print(f"INFO: Model has {len(all_classes)} classes")
        
        self._hazard_ids = set()
        self._vehicle_ids = set()
        
        for cls_id, cls_name in self.model.names.items():
            if cls_name in HAZARD_CLASSES:
                self._hazard_ids.add(cls_id)
            if cls_name in VEHICLE_CLASSES:
                self._vehicle_ids.add(cls_id)
        
        found_hazards = [self.model.names[i] for i in self._hazard_ids]
        found_vehicles = [self.model.names[i] for i in self._vehicle_ids]
        
        print(f"INFO: Hazard classes matched: {found_hazards}")
        print(f"INFO: Vehicle classes matched: {found_vehicles}")
        
        if not found_hazards:
            print(f"WARNING: None of {HAZARD_CLASSES} exist in model!")


        # all_classes = list(self.model.names.values())
        # print(f"INFO: Model has {len(all_classes)} classes")
        
        # # Cache .names once � repeatedly accessing self.model.names below
        # # was re-triggering the model backend to reload on ONNX models,
        # # once per lookup (13 extra reloads = 7 hazard + 6 vehicle classes).
        # model_names = self.model.names
        
        # self._hazard_ids = set()
        # self._vehicle_ids = set()
        
        # for cls_id, cls_name in model_names.items():
        #     if cls_name in HAZARD_CLASSES:
        #         self._hazard_ids.add(cls_id)
        #     if cls_name in VEHICLE_CLASSES:
        #         self._vehicle_ids.add(cls_id)
        
        # found_hazards = [model_names[i] for i in self._hazard_ids]
        # found_vehicles = [model_names[i] for i in self._vehicle_ids]
        
        # print(f"INFO: Hazard classes matched: {found_hazards}")
        # print(f"INFO: Vehicle classes matched: {found_vehicles}")
        
        # if not found_hazards:
        #     print(f"WARNING: None of {HAZARD_CLASSES} exist in model!")
        
        self.prev_vehicle_boxes = {}
        self.frame_count = 0

    def process_frame(self, frame):
        self.frame_count += 1
        
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            # Higher confidence to reduce false positives
            results = self.model(frame, conf=0.5, imgsz=320, verbose=False)[0]
        
        hazard_names = []
        urgent_vehicle_names = []
        
        if results.boxes is not None:
            boxes = results.boxes.data.cpu().numpy()
            
            for box in boxes:
                x1, y1, x2, y2, conf, cls_id = box
                cls_id = int(cls_id)
                class_name = self.model.names[cls_id]
                
                # Vehicle detection with approach speed
                if cls_id in self._vehicle_ids:
                    vehicle_id = f"{class_name}_{int(x1 // 100)}"
                    current_area = (x2 - x1) * (y2 - y1)
                    
                    if vehicle_id in self.prev_vehicle_boxes:
                        prev_area = self.prev_vehicle_boxes[vehicle_id]
                        if prev_area > 0:
                            expansion_rate = current_area / prev_area
                            if expansion_rate > 1.1:
                                urgent_vehicle_names.append(class_name)
                    
                    self.prev_vehicle_boxes[vehicle_id] = current_area
                
                # Hazard detection
                elif cls_id in self._hazard_ids:
                    box_area = (x2 - x1) * (y2 - y1)
                    frame_area = frame.shape[0] * frame.shape[1]
                    relative_size = box_area / frame_area
                    
                    # Must be at least 2% of frame AND minimum 2000 pixels
                    min_pixels = 2000
                    if relative_size > 0.02 and box_area > min_pixels:
                        hazard_names.append(class_name)
        
        annotated_frame = results.plot()
        
        return annotated_frame, hazard_names, urgent_vehicle_names
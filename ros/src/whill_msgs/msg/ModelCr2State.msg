# WHILL Model CR2 の Dataset1 相当。実機ドライバとモックが同じ型を publish する。
std_msgs/Header header

# LCD に出る 0-100 の値。二桁の数字はバッテリ残量であってエラーコードではない。
uint8 battery_power

float32 left_motor_angle          # rad
float32 right_motor_angle         # rad
float32 left_motor_speed          # rad/s
float32 right_motor_speed         # rad/s
float32 left_motor_current        # A
float32 right_motor_current       # A

int8 joystick_front               # -100..100
int8 joystick_side                # -100..100

uint8 speed_mode_indicator        # WHILL 本体の速度モード 0-5
bool power_on
bool error

uint8 error_code

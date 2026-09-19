using UnityEngine;
#if ENABLE_INPUT_SYSTEM
using UnityEngine.InputSystem;
#endif

namespace SurgePrep
{
    internal static class ShowcaseInput
    {
        public static bool Held(KeyCode key)
        {
#if ENABLE_INPUT_SYSTEM
            var keyboard = Keyboard.current;
            return keyboard != null && keyboard[InputSystemKey(key)].isPressed;
#elif ENABLE_LEGACY_INPUT_MANAGER
            return Input.GetKey(key);
#else
            return false;
#endif
        }

        public static bool Pressed(KeyCode key)
        {
#if ENABLE_INPUT_SYSTEM
            var keyboard = Keyboard.current;
            return keyboard != null && keyboard[InputSystemKey(key)].wasPressedThisFrame;
#elif ENABLE_LEGACY_INPUT_MANAGER
            return Input.GetKeyDown(key);
#else
            return false;
#endif
        }

        public static bool RightMouseHeld()
        {
#if ENABLE_INPUT_SYSTEM
            return Mouse.current != null && Mouse.current.rightButton.isPressed;
#elif ENABLE_LEGACY_INPUT_MANAGER
            return Input.GetMouseButton(1);
#else
            return false;
#endif
        }

        public static Vector2 MouseDelta()
        {
#if ENABLE_INPUT_SYSTEM
            return Mouse.current != null ? Mouse.current.delta.ReadValue() * 0.1f : Vector2.zero;
#elif ENABLE_LEGACY_INPUT_MANAGER
            return new Vector2(Input.GetAxis("Mouse X"), Input.GetAxis("Mouse Y"));
#else
            return Vector2.zero;
#endif
        }

        public static float MouseScroll()
        {
#if ENABLE_INPUT_SYSTEM
            if (Mouse.current == null) return 0f;
            var value = Mouse.current.scroll.ReadValue().y;
            return Mathf.Abs(value) < 0.001f ? 0f : Mathf.Sign(value) * Mathf.Max(0.1f, Mathf.Abs(value) / 120f);
#elif ENABLE_LEGACY_INPUT_MANAGER
            return Input.mouseScrollDelta.y;
#else
            return 0f;
#endif
        }

#if ENABLE_INPUT_SYSTEM
        private static Key InputSystemKey(KeyCode key)
        {
            switch (key)
            {
                case KeyCode.A: return Key.A;
                case KeyCode.C: return Key.C;
                case KeyCode.D: return Key.D;
                case KeyCode.O: return Key.O;
                case KeyCode.R: return Key.R;
                case KeyCode.S: return Key.S;
                case KeyCode.V: return Key.V;
                case KeyCode.W: return Key.W;
                case KeyCode.Space: return Key.Space;
                case KeyCode.LeftArrow: return Key.LeftArrow;
                case KeyCode.RightArrow: return Key.RightArrow;
                case KeyCode.UpArrow: return Key.UpArrow;
                case KeyCode.DownArrow: return Key.DownArrow;
                case KeyCode.LeftBracket: return Key.LeftBracket;
                case KeyCode.RightBracket: return Key.RightBracket;
                case KeyCode.Alpha1: return Key.Digit1;
                case KeyCode.Alpha2: return Key.Digit2;
                case KeyCode.Alpha3: return Key.Digit3;
                case KeyCode.Tab: return Key.Tab;
                default: return Key.None;
            }
        }
#endif
    }
}

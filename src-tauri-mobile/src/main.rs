// The desktop target exists only to run the mobile shell on a development machine.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    luminary_mobile_lib::run()
}

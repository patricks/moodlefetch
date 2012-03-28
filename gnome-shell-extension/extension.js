
const St = imports.gi.St;
const Main = imports.ui.main;
const Tweener = imports.ui.tweener;

const Util = imports.misc.util;

let text, button;

function _startMoodleFedch() {
    if (!text) {
        text = new St.Label({ style_class: 'moodlefetch-label', text: "running moodlefetch!" });
        Main.uiGroup.add_actor(text);
    }

    text.opacity = 255;

    let monitor = Main.layoutManager.primaryMonitor;

    text.set_position(Math.floor(monitor.width / 2 - text.width / 2),
                      Math.floor(monitor.height / 2 - text.height / 2));
      
    Util.trySpawnCommandLine('/usr/bin/python2.7 /home/manuel/git/github/moodlefetch/moodlefedch.py /home/manuel/.moodlefedch.cfg');

    Tweener.addTween(text,
                     { opacity: 0,
                       time: 3,
                       transition: 'easeOutQuad'});
}

function init() {
    button = new St.Bin({ style_class: 'panel-button',
                          reactive: true,
                          can_focus: true,
                          x_fill: true,
                          y_fill: false,
                          track_hover: true });
    let icon = new St.Icon({ icon_name: 'system-run',
                             icon_type: St.IconType.SYMBOLIC,
                             style_class: 'system-status-icon' });

    button.set_child(icon);
    button.connect('button-press-event', _startMoodleFedch);
}

function enable() {
    Main.panel._rightBox.insert_actor(button, 0);
}

function disable() {
    Main.panel._rightBox.remove_actor(button);
}

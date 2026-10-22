import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material

Button {
    id: control
    property bool working: false
    signal reveal(var control)
    highlighted: true
    implicitHeight: 48
    font.weight: Font.Medium
    enabled: !working
    Material.roundedScale: Material.FullScale
    onActiveFocusChanged: if (activeFocus) Qt.callLater(function() {
        if (control.activeFocus) control.reveal(control)
    })
}

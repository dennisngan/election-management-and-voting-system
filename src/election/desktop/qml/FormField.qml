import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts

TextField {
    id: control
    property bool working: false
    signal reveal(var control)
    Layout.fillWidth: true
    implicitHeight: 48
    selectByMouse: true
    enabled: !working
    Material.containerStyle: Material.Outlined
    onActiveFocusChanged: if (activeFocus) Qt.callLater(function() {
        if (control.activeFocus) control.reveal(control)
    })
}

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: page
    required property var snapshots
    required property var words
    property string locale: "tc"
    readonly property var editorState: snapshots.state
    readonly property var form: editorState.forms || ({})
    readonly property var context: editorState.context || ({})
    readonly property var election: context.election || ({})
    readonly property var station: context.station || ({})
    readonly property var selected: editorState.selected || ({})
    readonly property bool canCreate: !!editorState.station_id
        && editorState.role === "polling_officer"
        && (election.status === "draft" || election.status === "active")
    readonly property bool canEdit: canCreate && !editorState.historical
        && (!selected.id || editorState.editing)
    readonly property bool working: editorState.busy || editorState.refreshing
    signal reveal(var control)
    spacing: 20

    function t(key) { return words[key] || key }

    component Heading: Label {
        color: "#25344b"
        font.pixelSize: 20
        font.weight: Font.Medium
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
        Layout.fillWidth: true
    }
    component Detail: ColumnLayout {
        property string caption
        property string value
        spacing: 6
        Layout.fillWidth: true
        FormCaption { text: parent.caption }
        Label {
            text: parent.value
            color: "#25344b"
            font.pixelSize: 24
            textFormat: Text.PlainText
            wrapMode: Text.WrapAnywhere
            Layout.fillWidth: true
        }
    }

    RowLayout {
        Layout.fillWidth: true
        Heading { text: page.t("snapshot_title"); font.pixelSize: 28 }
        BusyIndicator {
            running: page.working
            visible: running
            implicitWidth: 28; implicitHeight: 28
            Accessible.name: page.t("loading")
        }
        FormButton {
            text: page.t("refresh")
            flat: true
            highlighted: false
            working: page.working
            onClicked: page.snapshots.refresh()
            onReveal: control => page.reveal(control)
        }
    }
    FormNotice {
        words: page.words
        error: page.editorState.error
        notice: page.editorState.notice
        onReveal: control => page.reveal(control)
    }
    FormPanel {
        implicitHeight: summary.implicitHeight + 40
        ColumnLayout {
            id: summary
            anchors.fill: parent; anchors.margins: 20
            spacing: 14
            Heading { text: page.station.name || page.t("select_station") }
            FormCaption { text: page.t("snapshot_intro") }
            FormCaption {
                objectName: "snapshotState"
                text: page.t("snapshot_" + page.editorState.snapshot_state)
                color: "#25344b"
                font.pixelSize: 16
            }
            FormCaption {
                visible: page.editorState.latest_basis_current === false
                text: page.t("snapshot_basis_stale")
                color: "#9a5b00"
            }
            FormCaption { text: page.t("snapshot_current_issued") }
            Label {
                objectName: "snapshotCurrentIssued"
                text: page.editorState.current_ordinary_issued_display
                color: "#1967d2"; font.pixelSize: 32
                textFormat: Text.PlainText
                wrapMode: Text.WrapAnywhere
                Layout.fillWidth: true
            }
            FormCaption { text: page.t("snapshot_provenance") }
        }
    }
    FormPanel {
        visible: !!page.editorState.station_id
        implicitHeight: formLayout.implicitHeight + 40
        ColumnLayout {
            id: formLayout
            anchors.fill: parent; anchors.margins: 20
            spacing: 16
            Heading { text: page.t("snapshot_observation") }
            FormCaption { text: page.t("snapshot_event_time") }
            FormField {
                objectName: "snapshotEventTime"
                text: page.form.event_time || ""
                readOnly: !page.canEdit
                working: page.working
                placeholderText: "YYYY-MM-DD HH:mm"
                Accessible.name: page.t("snapshot_event_time")
                onTextEdited: page.snapshots.setField("event_time", text)
                onReveal: control => page.reveal(control)
            }
            FormCaption { text: page.t("snapshot_reporting_hint") }
            Repeater {
                model: page.editorState.counter_reports.length
                delegate: FormPanel {
                    id: counterCard
                    required property int index
                    readonly property var row: page.editorState.counter_reports[index] || ({})
                    readonly property var counter: row.counter || ({})
                    implicitHeight: counterLayout.implicitHeight + 32
                    color: "#f7f9fd"; radius: 12
                    ColumnLayout {
                        id: counterLayout
                        anchors.fill: parent; anchors.margins: 16
                        spacing: 12
                        Heading { text: (counterCard.counter.code || "") + " · " + (counterCard.counter.name || "") }
                        CheckBox {
                            id: reported
                            objectName: "snapshotReported" + counterCard.counter.id
                            Layout.fillWidth: true
                            checked: counterCard.row.reported === true
                            enabled: page.canEdit && !page.working
                            text: page.t("snapshot_reported")
                            onClicked: page.snapshots.setCounterReported(counterCard.counter.id, checked)
                            onActiveFocusChanged: if (activeFocus) Qt.callLater(function() { page.reveal(reported) })
                        }
                        FormCaption {
                            visible: counterCard.row.reported && counterCard.row.ranges.length === 0
                            text: page.t("snapshot_explicit_zero")
                        }
                        Repeater {
                            model: counterCard.row.reported ? counterCard.row.ranges.length : 0
                            delegate: ColumnLayout {
                                id: rangeRow
                                required property int index
                                readonly property var row: counterCard.row.ranges[index] || ({})
                                readonly property string suffix: counterCard.counter.id + "_" + index
                                Layout.fillWidth: true
                                spacing: 8
                                FormCaption { text: page.t("stock_series") }
                                FormField {
                                    objectName: "snapshotSeries" + rangeRow.suffix
                                    text: rangeRow.row.series || ""
                                    readOnly: !page.canEdit
                                    working: page.working
                                    Accessible.name: page.t("stock_series")
                                    onTextEdited: page.snapshots.setRangeField(counterCard.counter.id, rangeRow.index, "series", text)
                                    onReveal: control => page.reveal(control)
                                }
                                GridLayout {
                                    Layout.fillWidth: true
                                    columns: page.width > 740 ? 3 : 1
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        FormCaption { text: page.t("stock_serial_from") }
                                        FormField {
                                            objectName: "snapshotSerialFrom" + rangeRow.suffix
                                            text: rangeRow.row.serial_from || ""
                                            readOnly: !page.canEdit
                                            working: page.working
                                            Accessible.name: page.t("stock_serial_from")
                                            onTextEdited: page.snapshots.setRangeField(counterCard.counter.id, rangeRow.index, "serial_from", text)
                                            onReveal: control => page.reveal(control)
                                        }
                                    }
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        FormCaption { text: page.t("stock_serial_to") }
                                        FormField {
                                            objectName: "snapshotSerialTo" + rangeRow.suffix
                                            text: rangeRow.row.serial_to || ""
                                            readOnly: !page.canEdit
                                            working: page.working
                                            Accessible.name: page.t("stock_serial_to")
                                            onTextEdited: page.snapshots.setRangeField(counterCard.counter.id, rangeRow.index, "serial_to", text)
                                            onReveal: control => page.reveal(control)
                                        }
                                    }
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        FormCaption { text: page.t("stock_range_quantity") }
                                        FormField {
                                            objectName: "snapshotQuantity" + rangeRow.suffix
                                            text: rangeRow.row.quantity_display || "—"
                                            readOnly: true
                                            Accessible.name: page.t("stock_range_quantity")
                                            onReveal: control => page.reveal(control)
                                        }
                                    }
                                }
                                FormButton {
                                    visible: page.canEdit
                                    text: page.t("stock_remove_range")
                                    highlighted: false; flat: true
                                    working: page.working
                                    onClicked: page.snapshots.removeRange(counterCard.counter.id, rangeRow.index)
                                    onReveal: control => page.reveal(control)
                                }
                            }
                        }
                        FormButton {
                            objectName: "snapshotAddRange" + counterCard.counter.id
                            visible: page.canEdit && counterCard.row.reported
                            text: page.t("snapshot_add_range")
                            highlighted: false
                            working: page.working
                            onClicked: page.snapshots.addRange(counterCard.counter.id)
                            onReveal: control => page.reveal(control)
                        }
                    }
                }
            }
            FormButton {
                objectName: "snapshotSave"
                visible: page.canEdit
                text: page.t("snapshot_save")
                working: page.working
                onClicked: page.snapshots.save()
                onReveal: control => page.reveal(control)
            }
        }
    }
    FormPanel {
        visible: !!page.selected.id
        implicitHeight: totalsLayout.implicitHeight + 40
        ColumnLayout {
            id: totalsLayout
            anchors.fill: parent; anchors.margins: 20
            spacing: 14
            Heading { text: page.t("snapshot_saved_totals") }
            GridLayout {
                Layout.fillWidth: true
                columns: page.width > 740 ? 3 : 1
                Detail { caption: page.t("snapshot_allocated"); value: page.editorState.totals.ordinary_allocated_display }
                Detail { caption: page.t("snapshot_returned"); value: page.editorState.totals.ordinary_returned_display }
                Detail { caption: page.t("snapshot_net"); value: page.editorState.totals.ordinary_net_allocated_display }
            }
            FormCaption { text: page.t("snapshot_remaining") }
            Label {
                objectName: "snapshotRemainingTotal"
                text: page.editorState.totals.ordinary_remaining_display
                color: "#25344b"; font.pixelSize: 24
                textFormat: Text.PlainText
                wrapMode: Text.WrapAnywhere
                Layout.fillWidth: true
            }
            Detail { caption: page.t("snapshot_issued"); value: page.editorState.totals.ordinary_issued_display }
        }
    }
}

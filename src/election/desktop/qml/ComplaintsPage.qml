pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: page
    required property var complaints
    required property var words
    required property string locale
    readonly property var editorState: complaints.state
    readonly property var context: editorState.context || ({})
    readonly property var selected: editorState.selected || ({})
    readonly property var form: editorState.forms || ({})
    readonly property var category: editorState.form_category || ({})
    readonly property bool hasStation: !!editorState.station_id
    readonly property bool canRecord: editorState.role === "polling_officer"
        && (context.election || ({})).status === "active"
    readonly property bool editable: hasStation && canRecord && !editorState.busy
        && !editorState.historical
    readonly property var categoryOptions: categories()
    readonly property var workStatuses: ["in_progress", "completed"]
    property string pendingAction: "reload"
    property int pendingValue: 0
    signal reveal(var control)
    spacing: 20

    function t(key) { return words[key] || key }
    function time(value) { return value ? complaints.formatTime(value) : "—" }
    function label(row) { return row["label_" + locale] || row.label_en || "—" }
    function caseCategory(row) { return row["category_label_" + locale] || row.category_label_en || "—" }
    function status(value) { return t(value === "completed" ? "complaint_completed" : "complaint_in_progress") }
    function categoryLabel(row) {
        return row.code + " · " + label(row) + " · " + t("revision") + " " + row.revision
    }
    function caseLabel(row) {
        return row.case_reference + " · " + caseCategory(row) + " · " + status(row.work_status)
            + " · " + t("revision") + " " + row.revision
    }
    function categories() {
        var result = []
        if (selected.id) result.push({
            id: selected.category_id, revision: selected.category_revision, code: selected.category_code,
            label_tc: selected.category_label_tc, label_sc: selected.category_label_sc,
            label_en: selected.category_label_en
        })
        var live = editorState.categories || []
        for (var i = 0; i < live.length; i++)
            if (live[i].enabled && (!selected.id || live[i].id !== selected.category_id))
                result.push(live[i])
        return result
    }
    function caseIndex() {
        for (var i = 0; i < editorState.items.length; i++)
            if (editorState.items[i].id === selected.id) return i
        return -1
    }
    function categoryIndex() {
        for (var i = 0; i < categoryOptions.length; i++)
            if (String(categoryOptions[i].id) === form.category_id) return i
        return -1
    }
    function choose(action, value) {
        if (editorState.busy) return
        var accepted = false
        if (action === "case") accepted = complaints.loadCase(value, false)
        else if (action === "revision") accepted = complaints.loadRevision(value, false)
        else accepted = complaints.reload(false)
        if (!accepted && editorState.dirty && editorState.error === "unsaved_complaint_changes") {
            pendingAction = action; pendingValue = value; discardDialog.open()
        }
        restorePickers()
    }
    function restorePickers() {
        casePicker.currentIndex = Qt.binding(function() { return page.caseIndex() })
        categoryPicker.currentIndex = Qt.binding(function() { return page.categoryIndex() })
        statusPicker.currentIndex = Qt.binding(function() { return page.form.work_status === "completed" ? 1 : 0 })
    }
    function moveFocus(control, forward) {
        var next = control.nextItemInFocusChain(forward)
        if (next) next.forceActiveFocus(forward ? Qt.TabFocusReason : Qt.BacktabFocusReason)
    }

    component Heading: Label {
        textFormat: Text.PlainText
        color: "#25344b"; font.pixelSize: 20; font.weight: Font.Medium
        wrapMode: Text.WordWrap; Layout.fillWidth: true
    }
    component Detail: ColumnLayout {
        id: detail
        required property string caption
        required property string value
        Layout.fillWidth: true; Layout.alignment: Qt.AlignTop; spacing: 6
        FormCaption { text: detail.caption }
        Label {
            text: detail.value; textFormat: Text.PlainText; color: "#25344b"
            wrapMode: Text.WrapAnywhere; Layout.fillWidth: true
        }
    }
    component Action: FormButton {
        id: action
        Layout.fillWidth: true
        implicitHeight: Math.max(48, contentItem.implicitHeight + 24)
        contentItem: Text {
            text: action.text; textFormat: Text.PlainText; font: action.font
            color: !action.enabled ? "#65758b" : action.highlighted ? "white" : "#1967d2"
            wrapMode: Text.WordWrap
            horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
        }
        onReveal: control => page.reveal(control)
    }
    component Picker: ComboBox {
        id: picker
        Layout.fillWidth: true
        implicitHeight: Math.max(48, contentItem.implicitHeight + topPadding + bottomPadding)
        contentItem: Text {
            text: picker.displayText; textFormat: Text.PlainText; font: picker.font
            color: picker.enabled ? "#25344b" : "#65758b"
            wrapMode: Text.WordWrap; verticalAlignment: Text.AlignVCenter
        }
        onActiveFocusChanged: if (activeFocus) Qt.callLater(function() {
            if (picker.activeFocus) page.reveal(picker)
        })
    }
    component Paragraph: TextArea {
        id: field
        Layout.fillWidth: true
        implicitHeight: Math.max(92, contentHeight + topPadding + bottomPadding)
        textFormat: TextEdit.PlainText; wrapMode: TextEdit.WordWrap
        selectByMouse: true; clip: true; padding: 12
        enabled: !page.editorState.busy; readOnly: !page.editable
        Keys.priority: Keys.BeforeItem
        Keys.onTabPressed: event => { page.moveFocus(field, true); event.accepted = true }
        Keys.onBacktabPressed: event => { page.moveFocus(field, false); event.accepted = true }
        onActiveFocusChanged: if (activeFocus) Qt.callLater(function() {
            if (field.activeFocus) page.reveal(field)
        })
        background: Rectangle {
            radius: 8; color: "white"
            border.color: field.activeFocus ? "#1967d2" : "#a7b2c2"
            border.width: field.activeFocus ? 2 : 1
        }
    }

    Connections {
        target: page.complaints
        function onStateChanged() { Qt.callLater(function() { page.restorePickers() }) }
    }

    RowLayout {
        Layout.fillWidth: true
        Heading { text: page.t("complaint_cases"); font.pixelSize: 28 }
        BusyIndicator {
            running: page.editorState.busy || page.editorState.refreshing
            visible: running; implicitWidth: 28; implicitHeight: 28
            Accessible.name: page.t("loading")
        }
        FormButton {
            objectName: "complaintRefresh"
            text: page.t("refresh"); flat: true; highlighted: false
            working: page.editorState.busy || page.editorState.refreshing
            enabled: page.hasStation && !working
            onClicked: page.complaints.refresh()
            onReveal: control => page.reveal(control)
        }
    }
    FormCaption { text: page.t("complaint_case_intro") }
    FormNotice {
        words: page.words; error: page.editorState.error; notice: page.editorState.notice
        onReveal: control => page.reveal(control)
    }
    FormCaption {
        objectName: "complaintNewerWarning"
        visible: !!page.editorState.newer_revision
        text: page.t("complaint_case_newer"); color: "#8a5c16"
    }
    FormCaption { visible: !page.hasStation; text: page.t("select_station") }
    FormCaption {
        visible: page.hasStation && !page.canRecord
        text: page.t("complaint_case_read_only")
    }
    FormPanel {
        visible: page.hasStation
        implicitHeight: listLayout.implicitHeight + 40
        ColumnLayout {
            id: listLayout
            anchors.fill: parent; anchors.margins: 20; spacing: 12
            Heading { text: page.t("complaint_case_list") }
            Picker {
                id: casePicker
                objectName: "complaintPicker"
                visible: page.editorState.items.length > 0
                enabled: !page.editorState.busy
                model: page.editorState.items
                currentIndex: page.caseIndex()
                displayText: currentIndex >= 0 ? page.caseLabel(page.selected) : page.t("complaint_case_select")
                Accessible.name: page.t("complaint_case_select")
                delegate: ItemDelegate {
                    id: caseOption
                    required property var modelData
                    required property int index
                    width: casePicker.width
                    implicitHeight: Math.max(48, contentItem.implicitHeight + topPadding + bottomPadding)
                    text: page.caseLabel(modelData)
                    highlighted: casePicker.highlightedIndex === index
                    contentItem: Text {
                        text: caseOption.text; textFormat: Text.PlainText; font: caseOption.font
                        color: "#25344b"; wrapMode: Text.WordWrap
                    }
                }
                onActivated: page.choose("case", model[currentIndex].id)
            }
            FormCaption { visible: page.editorState.items.length === 0; text: page.t("complaint_case_none") }
            RowLayout {
                Layout.fillWidth: true; spacing: 12
                Action {
                    objectName: "complaintNew"
                    visible: page.canRecord
                    text: page.t("complaint_case_new"); working: page.editorState.busy
                    onClicked: page.choose("case", 0)
                }
                Action {
                    objectName: "complaintReload"
                    text: page.t("reload_saved"); working: page.editorState.busy
                    flat: true; highlighted: false
                    onClicked: page.choose("reload", 0)
                }
            }
        }
    }
    FormPanel {
        visible: page.hasStation && (page.canRecord || !!page.selected.id)
        implicitHeight: formLayout.implicitHeight + 40
        ColumnLayout {
            id: formLayout
            anchors.fill: parent; anchors.margins: 20; spacing: 12
            Heading { text: page.selected.id ? page.selected.case_reference + " · " + page.t("revision") + " " + page.selected.revision : page.t("complaint_case_new") }
            FormCaption {
                visible: !!page.editorState.historical
                text: page.t("complaint_historical_readonly"); color: "#8a5c16"
            }
            FormCaption { text: page.t("complaint_case_reference") }
            FormField {
                objectName: "complaintReference"
                text: page.form.case_reference || ""; maximumLength: 64
                working: page.editorState.busy; readOnly: !page.editable
                Accessible.name: page.t("complaint_case_reference")
                onTextEdited: page.complaints.setField("case_reference", text)
                onReveal: control => page.reveal(control)
            }
            FormCaption { text: page.t("complaint_received_time") }
            FormField {
                objectName: "complaintReceivedTime"
                text: page.form.received_time || ""; placeholderText: "YYYY-MM-DD HH:mm"
                working: page.editorState.busy; readOnly: !page.editable
                Accessible.name: page.t("complaint_received_time")
                onTextEdited: page.complaints.setField("received_time", text)
                onReveal: control => page.reveal(control)
            }
            FormCaption { text: page.t("complaint_category_select") }
            Picker {
                id: categoryPicker
                objectName: "complaintCategory"
                enabled: page.editable
                model: page.categoryOptions
                currentIndex: page.categoryIndex()
                displayText: page.category.id ? page.categoryLabel(page.category) : page.t("complaint_category_select")
                Accessible.name: page.t("complaint_category_select")
                delegate: ItemDelegate {
                    id: categoryOption
                    required property var modelData
                    required property int index
                    width: categoryPicker.width
                    implicitHeight: Math.max(48, contentItem.implicitHeight + topPadding + bottomPadding)
                    text: page.categoryLabel(modelData)
                    highlighted: categoryPicker.highlightedIndex === index
                    contentItem: Text {
                        text: categoryOption.text; textFormat: Text.PlainText; font: categoryOption.font
                        color: "#25344b"; wrapMode: Text.WordWrap
                    }
                }
                onActivated: page.complaints.setField("category_id", String(model[currentIndex].id))
            }
            FormCaption {
                objectName: "complaintFrozenCategory"
                visible: !!page.category.frozen
                text: page.t("complaint_frozen_category")
            }
            Detail {
                objectName: "complaintCategorySource"
                visible: !!page.category.id
                caption: page.t("complaint_category_source")
                value: page.t(page.category.verified_source ? "complaint_verified_reference" : "complaint_project_configured")
                    + "\n" + (page.category.source_english || "—")
                    + "\n" + page.t("revision") + " " + (page.category.revision || "—")
                    + (page.category.reference_page ? " · " + page.t("complaint_reference_page") + " " + page.category.reference_page : "")
            }
            FormCaption { visible: !!page.category.id; text: page.t("complaint_translation_note") }
            FormCaption { text: page.t("complaint_case_description") }
            Paragraph {
                objectName: "complaintDescription"
                text: page.form.description || ""
                Accessible.name: page.t("complaint_case_description")
                onTextChanged: if (activeFocus && text !== page.form.description)
                    page.complaints.setField("description", text)
            }
            FormCaption {
                visible: !!page.category.is_other || !!page.category.description_required
                text: page.t("complaint_description_required")
            }
            FormCaption { text: page.t("complaint_work_status") }
            Picker {
                id: statusPicker
                objectName: "complaintWorkStatus"
                enabled: page.editable
                model: [page.t("complaint_in_progress"), page.t("complaint_completed")]
                currentIndex: page.form.work_status === "completed" ? 1 : 0
                Accessible.name: page.t("complaint_work_status")
                delegate: ItemDelegate {
                    id: statusOption
                    required property var modelData
                    required property int index
                    width: statusPicker.width
                    text: String(modelData)
                    highlighted: statusPicker.highlightedIndex === index
                    contentItem: Text {
                        text: statusOption.text; textFormat: Text.PlainText; font: statusOption.font
                        color: "#25344b"; wrapMode: Text.WordWrap
                    }
                }
                onActivated: page.complaints.setField("work_status", page.workStatuses[currentIndex])
            }
            FormCaption { visible: page.form.work_status === "completed"; text: page.t("complaint_completed_time") }
            FormField {
                objectName: "complaintCompletedTime"
                visible: page.form.work_status === "completed"
                text: page.form.completed_time || ""; placeholderText: "YYYY-MM-DD HH:mm"
                working: page.editorState.busy; readOnly: !page.editable
                Accessible.name: page.t("complaint_completed_time")
                onTextEdited: page.complaints.setField("completed_time", text)
                onReveal: control => page.reveal(control)
            }
            FormCaption { text: page.t("complaint_case_reason") }
            FormCaption { text: page.t("complaint_case_reason_hint") }
            Paragraph {
                objectName: "complaintReason"
                text: page.form.reason || ""
                Accessible.name: page.t("complaint_case_reason")
                onTextChanged: if (activeFocus && text !== page.form.reason)
                    page.complaints.setField("reason", text)
            }
            FormCaption {
                visible: !!page.selected.id && !!page.editorState.requires_amendment
                text: page.t("complaint_amendment_required")
            }
            RowLayout {
                Layout.fillWidth: true; spacing: 12
                Action {
                    objectName: "complaintCreate"
                    visible: page.canRecord && !page.selected.id
                    text: page.t("complaint_case_create"); working: page.editorState.busy
                    enabled: page.editable
                    onClicked: page.complaints.create()
                }
                Action {
                    objectName: "complaintEdit"
                    visible: page.canRecord && !!page.selected.id
                    text: page.t("complaint_case_edit"); working: page.editorState.busy
                    enabled: page.editable && !page.editorState.requires_amendment
                    onClicked: page.complaints.edit()
                }
                Action {
                    objectName: "complaintAmend"
                    visible: page.canRecord && !!page.selected.id && !!page.editorState.requires_amendment
                    text: page.t("complaint_case_amend"); working: page.editorState.busy
                    enabled: page.editable
                    onClicked: page.complaints.amend()
                }
            }
        }
    }
    FormPanel {
        visible: page.hasStation && !!page.selected.id
        implicitHeight: recordLayout.implicitHeight + 40
        ColumnLayout {
            id: recordLayout
            anchors.fill: parent; anchors.margins: 20; spacing: 12
            Detail {
                caption: page.t("complaint_received_period")
                value: page.selected.period_index ? String(page.selected.period_index) : "—"
            }
            FormCaption {
                objectName: "complaintOutsideCoverage"
                visible: page.selected.coverage_status === "outside_configured_periods"
                text: page.t("complaint_outside_coverage"); color: "#8a5c16"
            }
            Detail {
                caption: page.t("server_entry")
                value: page.time(page.selected.entered_at) + " · " + page.t("entered_by") + " " + (page.selected.actor_id || "—")
            }
        }
    }
    FormPanel {
        visible: page.hasStation
        implicitHeight: historyLayout.implicitHeight + 40
        ColumnLayout {
            id: historyLayout
            anchors.fill: parent; anchors.margins: 20; spacing: 16
            Heading { text: page.t("complaint_case_history") }
            FormCaption {
                visible: page.editorState.history.length === 0
                text: page.t("complaint_case_no_history")
            }
            Repeater {
                model: page.editorState.history
                delegate: ColumnLayout {
                    id: entry
                    required property var modelData
                    Layout.fillWidth: true; spacing: 12
                    Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: "#e1e7f0" }
                    Heading {
                        text: page.caseLabel(entry.modelData)
                        font.pixelSize: 17
                    }
                    Action {
                        objectName: "complaintHistoryRevision" + entry.modelData.revision
                        text: page.t("complaint_case_view_revision") + " · " + page.t("revision") + " " + entry.modelData.revision
                        flat: true; highlighted: false; working: page.editorState.busy
                        onClicked: page.choose("revision", entry.modelData.revision)
                    }
                    Detail { caption: page.t("complaint_received_time"); value: page.time(entry.modelData.received_at) }
                    Detail { caption: page.t("complaint_completed_time"); value: page.time(entry.modelData.completed_at) }
                    Detail { caption: page.t("complaint_case_description"); value: entry.modelData.description || "—" }
                    Detail { caption: page.t("complaint_case_reason"); value: entry.modelData.amendment_reason || "—" }
                    Detail {
                        caption: page.t("server_entry")
                        value: page.time(entry.modelData.entered_at) + " · " + page.t("entered_by") + " " + entry.modelData.actor_id
                    }
                }
            }
        }
    }
    ConfirmationDialog {
        id: discardDialog
        objectName: "complaintDiscardDialog"
        title: page.t("discard_changes"); message: page.t("unsaved_complaint_changes")
        acceptLabel: page.t("discard_changes"); rejectLabel: page.t("keep_editing")
        footer: DialogButtonBox {
            Button {
                objectName: "complaintKeepEditing"
                text: discardDialog.rejectLabel
                DialogButtonBox.buttonRole: DialogButtonBox.RejectRole
            }
            Button {
                objectName: "complaintDiscardChanges"
                text: discardDialog.acceptLabel
                DialogButtonBox.buttonRole: DialogButtonBox.AcceptRole
            }
        }
        onConfirmed: {
            if (page.pendingAction === "case") page.complaints.loadCase(page.pendingValue, true)
            else if (page.pendingAction === "revision") page.complaints.loadRevision(page.pendingValue, true)
            else page.complaints.reload(true)
        }
    }
}

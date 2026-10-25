pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: page
    objectName: "invalidReasonsPage"
    required property var catalog
    required property var words
    property string locale: "tc"
    readonly property var editorState: catalog.state
    readonly property var selected: editorState.selected || ({})
    readonly property var form: editorState.form || ({})
    readonly property bool editable: editorState.editing && !editorState.busy
        && !editorState.historical && !editorState.newer_revision
        && editorState.election.status !== "finalized"
    property string pendingAction: "reload"
    property int pendingId: 0
    property var electionRows: []
    property var reasonRows: []
    property var historyRows: []
    onLocaleChanged: Qt.callLater(function() { page.syncPickerModels() })
    signal reveal(var control)
    spacing: 20

    function t(key) { return words[key] || key }
    function label(row) { return row["label_" + locale] || row.label_en || "" }
    function reasonLabel(row) {
        return page.t("invalid_reason_code") + " " + row.code + " · " + page.label(row)
    }
    function indexOf(items, id) {
        for (var index = 0; index < items.length; index++)
            if (items[index].id === id) return index
        return -1
    }
    function syncPickerModels() {
        var state = catalog.state
        var elections = state.elections || []
        var reasons = state.items || []
        var history = (state.history || []).map(function(row) {
            return {revision: row.revision, label: page.historyLabel(row)}
        })
        if (!electionPicker.popup.visible
                && JSON.stringify(electionRows) !== JSON.stringify(elections))
            electionRows = elections.slice()
        if (!reasonPicker.popup.visible
                && JSON.stringify(reasonRows) !== JSON.stringify(reasons))
            reasonRows = reasons.slice()
        if (!historyPicker.popup.visible
                && JSON.stringify(historyRows) !== JSON.stringify(history))
            historyRows = history
    }
    function choose(action, id) {
        var accepted = action === "election" ? catalog.selectElection(id, false)
            : action === "reason" ? catalog.loadReason(id, false) : catalog.reload(false)
        if (!accepted && editorState.dirty) {
            pendingAction = action
            pendingId = id
            discardDialog.open()
        }
    }
    function historyLabel(row) {
        return t("invalid_reason_revision") + " " + row.revision
            + (row.enabled ? "" : " · " + t("invalid_reason_disabled"))
    }
    function historyIndex() {
        for (var index = 0; index < historyRows.length; index++)
            if (historyRows[index].revision === page.selected.revision) return index
        return -1
    }

    component Heading: Label {
        textFormat: Text.PlainText
        color: "#25344b"
        font.pixelSize: 20
        font.weight: Font.Medium
        Layout.fillWidth: true
        wrapMode: Text.WordWrap
    }
    component Action: FormButton {
        id: action
        Layout.fillWidth: true
        implicitWidth: 160
        implicitHeight: Math.max(48, actionText.implicitHeight + 24)
        contentItem: Text {
            id: actionText
            text: action.text
            textFormat: Text.PlainText
            font: action.font
            wrapMode: Text.WordWrap
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            color: action.enabled ? (action.highlighted ? "white" : "#1967d2") : "#8a96a8"
        }
        onReveal: control => page.reveal(control)
    }
    component Input: ColumnLayout {
        id: input
        required property string field
        required property string caption
        required property string controlName
        property bool immutable: false
        Layout.fillWidth: true
        spacing: 8
        FormCaption { text: input.caption }
        FormField {
            objectName: input.controlName
            text: page.form[input.field] || ""
            readOnly: !page.editable || input.immutable
            working: page.editorState.busy
            maximumLength: input.field === "code" ? 64 : 512
            Accessible.name: input.caption
            onTextEdited: page.catalog.setField(input.field, text)
            onReveal: control => page.reveal(control)
        }
    }
    component Picker: ComboBox {
        id: picker
        Layout.fillWidth: true
        enabled: !page.editorState.busy && !page.editorState.refreshing
        implicitHeight: Math.max(48, pickerText.implicitHeight + 24)
        contentItem: Text {
            id: pickerText
            text: picker.displayText
            textFormat: Text.PlainText
            font: picker.font
            color: "#25344b"
            wrapMode: Text.WordWrap
            verticalAlignment: Text.AlignVCenter
        }
        onActiveFocusChanged: if (activeFocus) Qt.callLater(function() {
            if (picker.activeFocus) page.reveal(picker)
        })
    }
    Connections {
        target: page.catalog
        function onStateChanged() { Qt.callLater(function() { page.syncPickerModels() }) }
    }
    Connections {
        target: electionPicker.popup
        function onVisibleChanged() {
            if (!electionPicker.popup.visible)
                Qt.callLater(function() { page.syncPickerModels() })
        }
    }
    Connections {
        target: reasonPicker.popup
        function onVisibleChanged() {
            if (!reasonPicker.popup.visible)
                Qt.callLater(function() { page.syncPickerModels() })
        }
    }
    Connections {
        target: historyPicker.popup
        function onVisibleChanged() {
            if (!historyPicker.popup.visible)
                Qt.callLater(function() { page.syncPickerModels() })
        }
    }
    Component.onCompleted: syncPickerModels()

    RowLayout {
        Layout.fillWidth: true
        Heading {
            objectName: "invalidReasonsTitle"
            text: page.t("invalid_reasons_title")
            font.pixelSize: 28
        }
        BusyIndicator {
            running: page.editorState.busy || page.editorState.refreshing
            visible: running
            implicitWidth: 28
            implicitHeight: 28
        }
        FormButton {
            objectName: "invalidReasonsRefresh"
            text: page.t("refresh")
            flat: true
            highlighted: false
            enabled: !page.editorState.busy && !page.editorState.refreshing
            onClicked: page.catalog.refresh()
            onReveal: control => page.reveal(control)
        }
    }
    FormCaption { text: page.t("invalid_reasons_hint") }
    FormNotice {
        objectName: "invalidReasonNotice"
        words: page.words
        error: page.editorState.error
        notice: page.editorState.notice
        autoReveal: !discardDialog.visible
        onReveal: control => page.reveal(control)
    }
    FormCaption {
        objectName: "invalidReasonNewerWarning"
        visible: page.editorState.newer_revision
        text: page.t("revision_conflict")
        color: "#8a5c16"
    }

    FormPanel {
        implicitHeight: selection.implicitHeight + 40
        ColumnLayout {
            id: selection
            anchors.fill: parent
            anchors.margins: 20
            spacing: 12
            FormCaption { text: page.t("selected_election") }
            Picker {
                id: electionPicker
                objectName: "invalidReasonElection"
                model: page.electionRows
                textRole: "name"
                currentIndex: page.indexOf(page.electionRows, page.editorState.election_id)
                Accessible.name: page.t("selected_election")
                onActivated: index => {
                    if (index >= 0) page.choose("election", model[index].id)
                }
            }
            FormCaption {
                visible: !!page.editorState.election_id
                text: page.t(page.editorState.election.status || "draft")
            }
            FormCaption { text: page.t("invalid_reason_select") }
            Picker {
                id: reasonPicker
                objectName: "invalidReasonPicker"
                model: page.reasonRows
                currentIndex: page.indexOf(page.reasonRows, page.selected.id)
                displayText: currentIndex >= 0
                    ? page.reasonLabel(model[currentIndex]) : page.t("invalid_reason_select")
                Accessible.name: page.t("invalid_reason_select")
                delegate: ItemDelegate {
                    id: option
                    required property var modelData
                    required property int index
                    width: reasonPicker.width
                    objectName: "invalidReasonOption_" + modelData.id
                    highlighted: reasonPicker.highlightedIndex === index
                    implicitHeight: Math.max(48, optionText.implicitHeight + 20)
                    contentItem: Text {
                        id: optionText
                        text: page.t("invalid_reason_code") + " " + option.modelData.code + " · "
                            + page.label(option.modelData)
                            + (option.modelData.enabled ? "" : " · " + page.t("invalid_reason_disabled"))
                        textFormat: Text.PlainText
                        font: option.font
                        color: "#25344b"
                        wrapMode: Text.WordWrap
                    }
                }
                onActivated: index => {
                    if (index >= 0) page.choose("reason", model[index].id)
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Action {
                    objectName: "invalidReasonNew"
                    text: page.t("invalid_reason_new")
                    highlighted: false
                    enabled: !!page.editorState.election_id
                        && page.editorState.election.status !== "finalized"
                        && !page.editorState.busy
                    onClicked: page.choose("reason", 0)
                }
                Action {
                    objectName: "invalidReasonReload"
                    text: page.t("reload_saved")
                    highlighted: false
                    enabled: !!page.editorState.election_id && !page.editorState.busy
                    onClicked: page.choose("reload", 0)
                }
            }
        }
    }

    FormPanel {
        visible: page.editorState.editing
        implicitHeight: editor.implicitHeight + 40
        ColumnLayout {
            id: editor
            anchors.fill: parent
            anchors.margins: 20
            spacing: 16
            Heading { text: page.selected.id ? page.label(page.selected) : page.t("editing_new") }
            FormCaption {
                visible: !!page.selected.id
                text: page.t("invalid_reason_revision") + " " + (page.selected.revision || "—")
                    + (page.editorState.dirty ? " •" : "")
            }
            FormCaption {
                visible: page.editorState.election.status === "finalized"
                text: page.t("invalid_reason_election_read_only")
            }
            FormCaption {
                visible: page.editorState.historical
                text: page.t("invalid_reason_historical")
            }
            RowLayout {
                visible: !!page.selected.id && page.editorState.history.length > 1
                FormCaption { text: page.t("invalid_reason_history") }
                Picker {
                    id: historyPicker
                    objectName: "invalidReasonHistory"
                    model: page.historyRows
                    currentIndex: page.historyIndex()
                    displayText: currentIndex >= 0 ? page.historyRows[currentIndex].label
                        : page.t("invalid_reason_history")
                    textRole: "label"
                    Accessible.name: page.t("invalid_reason_history")
                    onActivated: index => {
                        if (index >= 0) page.catalog.loadRevision(model[index].revision)
                    }
                }
            }
            Input {
                field: "code"; caption: page.t("invalid_reason_code")
                controlName: "invalidReasonCode"; immutable: !!page.selected.id
            }
            FormCaption {
                visible: !page.selected.id
                text: page.t("invalid_reason_create_help")
            }
            FormCaption {
                visible: page.editorState.editing
                text: page.t("invalid_reason_stage") + ": " + page.t("invalid_reason_f1")
            }
            Input {
                field: "label_tc"; caption: page.t("invalid_reason_label_tc")
                controlName: "invalidReasonLabelTc"
            }
            Input {
                field: "label_sc"; caption: page.t("invalid_reason_label_sc")
                controlName: "invalidReasonLabelSc"
            }
            Input {
                field: "label_en"; caption: page.t("invalid_reason_label_en")
                controlName: "invalidReasonLabelEn"
            }
            CheckBox {
                id: enabledCheck
                objectName: "invalidReasonEnabled"
                text: page.t("invalid_reason_enabled")
                checked: !!page.form.enabled
                enabled: page.editable && !page.selected.is_other
                onClicked: page.catalog.setEnabled(checked)
                onActiveFocusChanged: if (activeFocus) Qt.callLater(function() {
                    if (enabledCheck.activeFocus) page.reveal(enabledCheck)
                })
            }
            CheckBox {
                id: explanationCheck
                objectName: "invalidReasonExplanationRequired"
                text: page.t("invalid_reason_explanation_required")
                checked: !!page.form.explanation_required
                enabled: page.editable && !page.selected.is_other
                onClicked: page.catalog.setExplanationRequired(checked)
                onActiveFocusChanged: if (activeFocus) Qt.callLater(function() {
                    if (explanationCheck.activeFocus) page.reveal(explanationCheck)
                })
            }
            FormCaption {
                visible: !!page.selected.is_other
                text: page.t("invalid_reason_other_note")
            }
            Heading { text: page.t("invalid_reason_source"); font.pixelSize: 17 }
            FormCaption {
                visible: !!page.selected.id
                text: page.t(page.selected.verified_source
                    ? "invalid_reason_source_verified" : "invalid_reason_source_project")
            }
            FormCaption {
                objectName: "invalidReasonSourceEnglish"
                visible: !!page.selected.source_english
                text: page.t("invalid_reason_source_english") + ": " + page.selected.source_english
            }
            FormCaption {
                visible: !!page.selected.source_letter
                text: page.t("invalid_reason_source_letter") + ": " + page.selected.source_letter
            }
            FormCaption {
                visible: !!page.selected.reference_page
                text: page.t("invalid_reason_reference_page") + ": " + page.selected.reference_page
            }
            FormCaption {
                visible: !!page.selected.reference_printed_page
                text: page.t("invalid_reason_printed_page") + ": "
                    + page.selected.reference_printed_page
            }
            FormCaption {
                visible: !!page.selected.id
                text: page.t("invalid_reason_translation_provenance") + ": "
                    + page.t("invalid_reason_project_translation")
            }
            FormCaption {
                visible: !!page.selected.id
                text: page.t("invalid_reason_source_note")
                wrapMode: Text.WordWrap
            }
            Action {
                objectName: "invalidReasonSave"
                text: page.t("invalid_reason_save")
                highlighted: true
                working: page.editorState.busy
                visible: page.editorState.editing
                enabled: page.editable && page.editorState.dirty
                    && !page.editorState.newer_revision
                onClicked: page.catalog.save()
            }
        }
    }

    ConfirmationDialog {
        id: discardDialog
        objectName: "invalidReasonDiscardDialog"
        focus: true
        title: page.t("discard_changes")
        message: page.t("unsaved_invalid_reason_changes")
        acceptLabel: page.t("discard_changes")
        rejectLabel: page.t("keep_editing")
        onConfirmed: {
            if (page.pendingAction === "election")
                page.catalog.selectElection(page.pendingId, true)
            else if (page.pendingAction === "reason")
                page.catalog.loadReason(page.pendingId, true)
            else
                page.catalog.reload(true)
            page.syncPickerModels()
        }
    }
}

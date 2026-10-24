pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import QtCore

ColumnLayout {
    id: page
    required property var turnout
    required property var words
    property string locale: "tc"
    readonly property var editorState: turnout.state
    readonly property var selected: editorState.selected || ({})
    readonly property var current: editorState.current || ({})
    readonly property var reviewedPeriod: editorState.selected_period_context || ({})
    readonly property var form: editorState.forms || ({})
    readonly property var context: editorState.context || ({})
    readonly property var schedule: editorState.schedule || ({})
    readonly property var prefix: editorState.approved_prefix || ({})
    readonly property var sourceModes: ["normal", "fallback", "recovery"]
    readonly property string sourceMode: form.mode || "normal"
    readonly property var sourceBasis: selected.source_basis_display || ({})
    readonly property bool hasStation: !!editorState.station_id
    readonly property bool hasReviewedPeriod: !!reviewedPeriod.period_index
        && reviewedPeriod.period_index === editorState.selected_period
    readonly property bool pollingOfficer: editorState.role === "polling_officer"
    readonly property bool supervisor: editorState.role === "supervisor"
    readonly property bool activeElection: !!context.election && context.election.status === "active"
    readonly property bool editable: pollingOfficer && activeElection && hasReviewedPeriod
        && !editorState.busy && !editorState.historical
    readonly property bool draft: !selected.revision || selected.status === "draft"
    readonly property bool amendable: selected.status === "submitted" || selected.status === "approved"
    readonly property bool canApprove: supervisor && activeElection && hasReviewedPeriod
        && selected.status === "submitted" && !editorState.busy && !editorState.dirty
        && !editorState.historical && !editorState.newer_revision
    property string pendingAction: "reload"
    property var pendingValue: 0
    property string pendingFormat: "pdf"
    property string pendingLocale: "tc"
    property bool pendingStationReport: false
    signal reveal(var control)
    spacing: 20

    function t(key) { return words[key] || key }
    function sourceModeIndex() { return Math.max(0, sourceModes.indexOf(sourceMode)) }
    function sourceModeLabel(mode) { return t("turnout_mode_" + mode) }
    function exact(value) { return value === undefined || value === null ? "—" : value }
    function time(value) { return value ? turnout.formatTime(value) : "—" }
    function languageName(code) {
        return code === "sc" ? "简体中文" : code === "en" ? "English" : "繁體中文"
    }
    function previewReport() {
        if (reportScope.currentIndex === 1) turnout.previewStation(locale)
        else turnout.preview(locale)
    }
    function exportReport(format) {
        if (!hasStation || editorState.busy) return
        pendingFormat = format
        pendingLocale = locale
        pendingStationReport = reportScope.currentIndex === 1
        exportDialog.nameFilters = format === "pdf" ? ["PDF (*.pdf)"] : ["CSV (*.csv)"]
        exportDialog.defaultSuffix = format
        var basis = pendingStationReport ? "station-current"
            : "period-" + selected.period_index + "-revision-" + selected.revision
        exportDialog.selectedFile = exportDialog.currentFolder.toString() + "/p15-"
            + editorState.station_id + "-" + basis + "-" + locale + "." + format
        exportDialog.open()
    }
    function selectedIndex() {
        for (let i = 0; i < editorState.items.length; i++)
            if (editorState.items[i].period_index === editorState.selected_period) return i
        return -1
    }
    function periodLabel(row) {
        return t("turnout_period") + " " + row.period_index_display + " · "
            + time(row.start_at) + " → " + time(row.end_at) + " · " + t(row.status)
    }
    function restorePicker() {
        periodPicker.currentIndex = Qt.binding(function() { return page.selectedIndex() })
    }
    function choose(action, value) {
        if (editorState.busy) return
        var accepted = false
        if (action === "period") accepted = turnout.selectPeriod(value, false)
        else if (action === "page") accepted = turnout.setPage(value, false)
        else if (action === "revision") accepted = turnout.loadRevision(value, false)
        else accepted = turnout.reload(false)
        if (!accepted && editorState.dirty && editorState.error === "unsaved_turnout_changes") {
            pendingAction = action
            pendingValue = value
            discardDialog.open()
        }
        restorePicker()
    }
    function gotoPeriod() {
        var input = gotoField.text.trim()
        var ordinal = /^[0-9]+$/.test(input) ? Number(input) : 0
        if (!isFinite(ordinal) || Math.floor(ordinal) !== ordinal
                || ordinal < 1 || ordinal > editorState.period_count) ordinal = 0
        choose("period", ordinal)
    }
    function moveFocus(control, forward) {
        var next = control.nextItemInFocusChain(forward)
        if (next) next.forceActiveFocus(forward ? Qt.TabFocusReason : Qt.BacktabFocusReason)
    }
    function basis(row) {
        if (!row || row.status !== "approved") return "—"
        if (!row.basis_predecessor_record_id) return t("turnout_first_baseline")
        return t("turnout_basis_record") + " " + row.basis_predecessor_record_id
            + " · " + t("revision") + " " + row.basis_predecessor_revision
    }

    component Heading: Label {
        textFormat: Text.PlainText
        color: "#25344b"
        font.pixelSize: 20
        font.weight: Font.Medium
        wrapMode: Text.WordWrap
        Layout.fillWidth: true
    }
    component Detail: ColumnLayout {
        id: detail
        required property string caption
        required property string value
        Layout.fillWidth: true
        Layout.alignment: Qt.AlignTop
        spacing: 6
        FormCaption { text: detail.caption }
        Label {
            objectName: detail.objectName ? detail.objectName + "Value" : ""
            text: detail.value
            textFormat: Text.PlainText
            color: "#25344b"
            font.pixelSize: 15
            wrapMode: Text.WrapAnywhere
            Layout.fillWidth: true
        }
    }
    component ActionButton: FormButton {
        id: actionControl
        Layout.fillWidth: true
        implicitWidth: 160
        implicitHeight: Math.max(48, actionLabel.implicitHeight + 24)
        contentItem: Text {
            id: actionLabel
            text: actionControl.text
            textFormat: Text.PlainText
            font: actionControl.font
            wrapMode: Text.WordWrap
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            color: actionControl.enabled ? (actionControl.highlighted ? "white" : "#1967d2") : "#8a96a8"
        }
        onReveal: control => page.reveal(control)
    }
    component ReasonTextArea: TextArea {
        id: field
        property string caption: ""
        Layout.fillWidth: true
        implicitHeight: Math.max(92, contentHeight + topPadding + bottomPadding)
        textFormat: TextEdit.PlainText
        wrapMode: TextEdit.WordWrap
        clip: true
        selectByMouse: true
        enabled: !page.editorState.busy
        leftPadding: 12
        rightPadding: 12
        topPadding: 12
        bottomPadding: 12
        topInset: 0
        Accessible.name: caption
        Keys.priority: Keys.BeforeItem
        Keys.onTabPressed: event => { page.moveFocus(field, true); event.accepted = true }
        Keys.onBacktabPressed: event => { page.moveFocus(field, false); event.accepted = true }
        onActiveFocusChanged: if (activeFocus) Qt.callLater(function() {
            if (field.activeFocus) page.reveal(field)
        })
        background: Rectangle {
            radius: 8
            color: "white"
            border.color: field.activeFocus ? "#1967d2" : "#a7b2c2"
            border.width: field.activeFocus ? 2 : 1
        }
    }

    Connections {
        target: page.turnout
        function onErasePassword() { approvalPassword.clear() }
        function onStateChanged() { Qt.callLater(function() { page.restorePicker() }) }
    }

    RowLayout {
        Layout.fillWidth: true
        Heading { text: page.t("turnout_title"); font.pixelSize: 28 }
        BusyIndicator {
            running: page.editorState.busy || page.editorState.refreshing
            visible: running
            implicitWidth: 28
            implicitHeight: 28
            Accessible.name: page.t("loading")
        }
        FormButton {
            objectName: "turnoutRefresh"
            text: page.t("refresh")
            flat: true
            highlighted: false
            working: page.editorState.busy || page.editorState.refreshing
            enabled: page.hasStation && !working
            onClicked: page.turnout.refresh()
            onReveal: control => page.reveal(control)
        }
    }
    FormCaption { text: page.t("turnout_intro") }
    FormNotice {
        objectName: "turnoutNotice"
        words: page.words
        error: page.editorState.error
        notice: page.editorState.notice
        onReveal: control => page.reveal(control)
    }
    FormCaption {
        objectName: "turnoutNewerWarning"
        visible: !!page.editorState.newer_revision
        text: page.t("turnout_newer_revision")
        color: "#8a5c16"
    }
    FormCaption { visible: !page.hasStation; text: page.t("select_station") }

    FormPanel {
        visible: page.hasStation
        implicitHeight: coverage.implicitHeight + 40
        ColumnLayout {
            id: coverage
            anchors.fill: parent
            anchors.margins: 20
            spacing: 16
            Heading { text: page.t("turnout_approved_coverage") }
            FormCaption { text: page.t("turnout_coverage_hint") }
            GridLayout {
                Layout.fillWidth: true
                columns: page.width > 900 ? 3 : 1
                columnSpacing: 24
                rowSpacing: 16
                Detail {
                    caption: page.t("turnout_approved_total")
                    value: page.prefix.cumulative_end_display || "—"
                }
                Detail {
                    caption: page.t("turnout_approved_periods")
                    value: page.prefix.periods_display || "0"
                }
                Detail {
                    caption: page.t("turnout_covered_until")
                    value: page.time(page.prefix.covered_until)
                }
            }
            FormCaption { text: page.t("turnout_baseline_hint") }
            Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: "#e1e7f0" }
            Heading { text: page.t("turnout_configured_schedule"); font.pixelSize: 17 }
            GridLayout {
                Layout.fillWidth: true
                columns: page.width > 780 ? 2 : 1
                columnSpacing: 24
                rowSpacing: 16
                Detail { caption: page.t("planned_opening"); value: page.time(page.schedule.planned_opening_at) }
                Detail { caption: page.t("planned_closing"); value: page.time(page.schedule.planned_closing_at) }
            }
            FormCaption {
                text: page.t("reporting_interval") + " · " + (page.schedule.reporting_interval_minutes || "—")
                    + "   " + page.t("turnout_total_periods") + " · " + page.editorState.period_count_display
            }
        }
    }

    FormPanel {
        visible: page.hasStation
        implicitHeight: navigation.implicitHeight + 40
        ColumnLayout {
            id: navigation
            anchors.fill: parent
            anchors.margins: 20
            spacing: 14
            Heading { text: page.t("turnout_select_period") }
            ComboBox {
                id: periodPicker
                objectName: "turnoutPeriodPicker"
                Layout.fillWidth: true
                model: page.editorState.items
                currentIndex: page.selectedIndex()
                displayText: currentIndex >= 0 && currentIndex < model.length
                    ? page.periodLabel(model[currentIndex]) : page.t("turnout_select_period")
                enabled: !page.editorState.busy
                implicitHeight: Math.max(48, pickerText.implicitHeight + 24)
                Accessible.name: page.t("turnout_select_period")
                contentItem: Text {
                    id: pickerText
                    text: periodPicker.displayText
                    textFormat: Text.PlainText
                    font: periodPicker.font
                    color: "#25344b"
                    wrapMode: Text.WordWrap
                    verticalAlignment: Text.AlignVCenter
                }
                delegate: ItemDelegate {
                    id: option
                    required property var modelData
                    required property int index
                    width: periodPicker.width
                    highlighted: periodPicker.highlightedIndex === index
                    implicitHeight: Math.max(48, optionText.implicitHeight + 20)
                    contentItem: Text {
                        id: optionText
                        text: page.periodLabel(option.modelData)
                        textFormat: Text.PlainText
                        font: option.font
                        color: "#25344b"
                        wrapMode: Text.WordWrap
                        verticalAlignment: Text.AlignVCenter
                    }
                }
                onActivated: index => {
                    var row = model[index]
                    if (row) page.choose("period", row.period_index)
                    page.restorePicker()
                }
                onActiveFocusChanged: if (activeFocus) Qt.callLater(function() {
                    if (periodPicker.activeFocus) page.reveal(periodPicker)
                })
            }
            FormCaption {
                text: page.t("turnout_visible_periods") + " · " + page.editorState.items.length
                    + " / " + page.editorState.period_count_display
            }
            GridLayout {
                Layout.fillWidth: true
                columns: page.width > 640 ? 2 : 1
                columnSpacing: 12
                rowSpacing: 12
                ActionButton {
                    objectName: "turnoutPreviousPage"
                    text: page.t("turnout_previous_page")
                    highlighted: false
                    flat: true
                    working: page.editorState.busy
                    enabled: !working && page.editorState.offset > 0
                    onClicked: page.choose("page", Math.max(0, page.editorState.offset - page.editorState.limit))
                }
                ActionButton {
                    objectName: "turnoutNextPage"
                    text: page.t("turnout_next_page")
                    highlighted: false
                    flat: true
                    working: page.editorState.busy
                    enabled: !working && page.editorState.offset + page.editorState.limit < page.editorState.period_count
                    onClicked: page.choose("page", page.editorState.offset + page.editorState.limit)
                }
            }
            GridLayout {
                Layout.fillWidth: true
                columns: page.width > 640 ? 2 : 1
                columnSpacing: 12
                rowSpacing: 8
                FormField {
                    id: gotoField
                    objectName: "turnoutGotoPeriod"
                    maximumLength: 10
                    placeholderText: page.t("turnout_goto_period")
                    working: page.editorState.busy
                    Accessible.name: page.t("turnout_goto_period")
                    onAccepted: page.gotoPeriod()
                    onReveal: control => page.reveal(control)
                }
                ActionButton {
                    objectName: "turnoutGotoButton"
                    text: page.t("turnout_goto_action")
                    highlighted: false
                    working: page.editorState.busy
                    enabled: !working && !!gotoField.text.trim()
                    onClicked: page.gotoPeriod()
                }
            }
            ActionButton {
                objectName: "turnoutReload"
                text: page.t("reload_saved")
                highlighted: false
                flat: true
                working: page.editorState.busy
                onClicked: page.choose("reload", 0)
            }
        }
    }

    FormPanel {
        visible: page.hasStation && page.hasReviewedPeriod
        implicitHeight: editor.implicitHeight + 40
        ColumnLayout {
            id: editor
            anchors.fill: parent
            anchors.margins: 20
            spacing: 16
            Heading { text: page.t("turnout_reviewed_period") }
            FormCaption {
                text: page.t("turnout_period") + " " + page.reviewedPeriod.period_index
                    + " · " + page.time(page.reviewedPeriod.start_at) + " → " + page.time(page.reviewedPeriod.end_at)
            }
            FormCaption {
                text: page.t(page.selected.status || "missing") + " · " + page.t("revision")
                    + " " + (page.selected.revision || "—") + (page.editorState.dirty ? " •" : "")
            }
            FormCaption {
                visible: !!page.editorState.historical
                text: page.t("turnout_historical")
                color: "#8a5c16"
            }
            Detail {
                caption: page.t("turnout_live_state")
                value: page.t(page.current.status || "missing") + "\n"
                    + page.t(page.current.approval_valid ? "turnout_approval_valid"
                        : page.current.review_required ? "turnout_review_invalid" : "turnout_not_approved")
            }
            GridLayout {
                Layout.fillWidth: true
                columns: page.width > 900 ? 3 : 1
                columnSpacing: 24
                rowSpacing: 16
                Detail { caption: page.t("turnout_derived_hourly"); value: page.selected.derived_hourly_display || "—" }
                Detail { caption: page.t("turnout_derived_start"); value: page.selected.derived_cumulative_start_display || "—" }
                Detail { caption: page.t("turnout_derived_end"); value: page.selected.derived_cumulative_end_display || "—" }
            }
            FormCaption { text: page.t("turnout_source_mode") }
            ComboBox {
                id: sourceModePicker
                objectName: "turnoutSourceMode"
                Layout.fillWidth: true
                model: page.sourceModes.map(mode => page.sourceModeLabel(mode))
                currentIndex: page.sourceModeIndex()
                enabled: page.editable
                implicitHeight: Math.max(48, sourceModeText.implicitHeight + 24)
                Accessible.name: page.t("turnout_source_mode")
                contentItem: Text {
                    id: sourceModeText
                    text: sourceModePicker.displayText
                    textFormat: Text.PlainText
                    font: sourceModePicker.font
                    color: "#25344b"
                    wrapMode: Text.WordWrap
                    verticalAlignment: Text.AlignVCenter
                }
                delegate: ItemDelegate {
                    id: sourceModeOption
                    required property string modelData
                    required property int index
                    width: sourceModePicker.width
                    highlighted: sourceModePicker.highlightedIndex === index
                    implicitHeight: Math.max(48, sourceModeOptionText.implicitHeight + 20)
                    contentItem: Text {
                        id: sourceModeOptionText
                        text: sourceModeOption.modelData
                        textFormat: Text.PlainText
                        font: sourceModeOption.font
                        color: "#25344b"
                        wrapMode: Text.WordWrap
                        verticalAlignment: Text.AlignVCenter
                    }
                }
                onActivated: index => {
                    page.turnout.setField("mode", page.sourceModes[index])
                    currentIndex = Qt.binding(function() { return page.sourceModeIndex() })
                }
                onActiveFocusChanged: if (activeFocus) Qt.callLater(function() {
                    if (sourceModePicker.activeFocus) page.reveal(sourceModePicker)
                })
            }
            FormCaption { visible: page.sourceMode === "normal"; text: page.t("external_manual") }
            FormCaption {
                text: page.t(page.sourceMode === "fallback" ? "turnout_fallback_source_hint"
                    : page.sourceMode === "recovery" ? "turnout_recovery_source_hint"
                    : "turnout_optional_counts_hint")
            }
            GridLayout {
                visible: page.sourceMode === "fallback"
                Layout.fillWidth: true
                columns: page.width > 780 ? 2 : 1
                columnSpacing: 24
                rowSpacing: 16
                ColumnLayout {
                    Layout.fillWidth: true
                    FormCaption { text: page.t("turnout_activation_id") }
                    FormField {
                        objectName: "turnoutFallbackActivationId"
                        text: page.form.fallback_activation_id || ""
                        readOnly: !page.editable
                        working: page.editorState.busy
                        Accessible.name: page.t("turnout_activation_id")
                        onTextEdited: page.turnout.setField("fallback_activation_id", text)
                        onReveal: control => page.reveal(control)
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    FormCaption { text: page.t("turnout_activation_revision") }
                    FormField {
                        objectName: "turnoutFallbackActivationRevision"
                        text: page.form.fallback_activation_revision || ""
                        readOnly: !page.editable
                        working: page.editorState.busy
                        Accessible.name: page.t("turnout_activation_revision")
                        onTextEdited: page.turnout.setField("fallback_activation_revision", text)
                        onReveal: control => page.reveal(control)
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    FormCaption { text: page.t("turnout_snapshot_id") }
                    FormField {
                        objectName: "turnoutStockSnapshotId"
                        text: page.form.stock_snapshot_id || ""
                        readOnly: !page.editable
                        working: page.editorState.busy
                        Accessible.name: page.t("turnout_snapshot_id")
                        onTextEdited: page.turnout.setField("stock_snapshot_id", text)
                        onReveal: control => page.reveal(control)
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    FormCaption { text: page.t("turnout_snapshot_revision") }
                    FormField {
                        objectName: "turnoutStockSnapshotRevision"
                        text: page.form.stock_snapshot_revision || ""
                        readOnly: !page.editable
                        working: page.editorState.busy
                        Accessible.name: page.t("turnout_snapshot_revision")
                        onTextEdited: page.turnout.setField("stock_snapshot_revision", text)
                        onReveal: control => page.reveal(control)
                    }
                }
            }
            GridLayout {
                visible: page.sourceMode === "recovery"
                Layout.fillWidth: true
                columns: page.width > 780 ? 2 : 1
                columnSpacing: 24
                rowSpacing: 16
                ColumnLayout {
                    Layout.fillWidth: true
                    FormCaption { text: page.t("turnout_recovery_id") }
                    FormField {
                        objectName: "turnoutFallbackRecoveryId"
                        text: page.form.fallback_recovery_id || ""
                        readOnly: !page.editable
                        working: page.editorState.busy
                        Accessible.name: page.t("turnout_recovery_id")
                        onTextEdited: page.turnout.setField("fallback_recovery_id", text)
                        onReveal: control => page.reveal(control)
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    FormCaption { text: page.t("turnout_recovery_revision") }
                    FormField {
                        objectName: "turnoutFallbackRecoveryRevision"
                        text: page.form.fallback_recovery_revision || ""
                        readOnly: !page.editable
                        working: page.editorState.busy
                        Accessible.name: page.t("turnout_recovery_revision")
                        onTextEdited: page.turnout.setField("fallback_recovery_revision", text)
                        onReveal: control => page.reveal(control)
                    }
                }
            }
            FormCaption { visible: !page.pollingOfficer; text: page.t("turnout_read_only") }
            FormCaption {
                visible: !page.activeElection
                text: page.t(page.context.election && page.context.election.status === "finalized"
                    ? "election_read_only" : "active_election_required")
            }
            GridLayout {
                Layout.fillWidth: true
                columns: page.width > 780 ? 2 : 1
                columnSpacing: 24
                rowSpacing: 16
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    FormCaption { text: page.t("turnout_supplied_hourly") }
                    FormField {
                        objectName: "turnoutHourly"
                        text: page.form.supplied_hourly || ""
                        readOnly: !page.editable || page.sourceMode === "fallback"
                        working: page.editorState.busy
                        Accessible.name: page.t("turnout_supplied_hourly")
                        onTextEdited: page.turnout.setField("supplied_hourly", text)
                        onReveal: control => page.reveal(control)
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    FormCaption { text: page.t("turnout_supplied_cumulative") }
                    FormField {
                        objectName: "turnoutCumulative"
                        text: page.form.supplied_cumulative || ""
                        readOnly: !page.editable || page.sourceMode === "fallback"
                        working: page.editorState.busy
                        Accessible.name: page.t("turnout_supplied_cumulative")
                        onTextEdited: page.turnout.setField("supplied_cumulative", text)
                        onReveal: control => page.reveal(control)
                    }
                }
            }
            FormCaption { text: page.t("turnout_event_time") }
            FormField {
                objectName: "turnoutEventTime"
                text: page.form.event_time || ""
                placeholderText: "YYYY-MM-DD HH:mm"
                readOnly: !page.editable
                working: page.editorState.busy
                Accessible.name: page.t("turnout_event_time")
                onTextEdited: page.turnout.setField("event_time", text)
                onReveal: control => page.reveal(control)
            }
            FormCaption { text: page.t("turnout_time_hint") }
            FormCaption { text: page.t("turnout_source_context") }
            ReasonTextArea {
                objectName: "turnoutSource"
                caption: page.t("turnout_source_context")
                text: page.form.source_context || ""
                readOnly: !page.editable
                onTextEdited: page.turnout.setField("source_context", text)
            }
            Detail {
                visible: !!page.selected.amendment_reason && !page.amendable
                caption: page.t("amendment_reason")
                value: page.selected.amendment_reason || "—"
            }
            ColumnLayout {
                visible: page.pollingOfficer && page.amendable
                Layout.fillWidth: true
                spacing: 8
                FormCaption { text: page.t("turnout_amendment_hint") }
                FormCaption { text: page.t("amendment_reason") }
                ReasonTextArea {
                    objectName: "turnoutAmendmentReason"
                    caption: page.t("amendment_reason")
                    text: page.form.amendment_reason || ""
                    readOnly: !page.editable
                    onTextEdited: page.turnout.setField("amendment_reason", text)
                }
            }
            FormCaption {
                visible: !!page.editorState.dirty
                text: page.t("unsaved_turnout_changes")
                color: "#8a5c16"
            }
            GridLayout {
                visible: page.pollingOfficer
                Layout.fillWidth: true
                columns: page.width > 780 ? 2 : 1
                columnSpacing: 12
                rowSpacing: 12
                ActionButton {
                    objectName: "turnoutSave"
                    visible: page.draft
                    text: page.t("turnout_save")
                    working: page.editorState.busy
                    enabled: page.editable && page.draft && !page.editorState.newer_revision
                        && (!page.selected.revision || page.editorState.dirty)
                    onClicked: page.turnout.save()
                }
                ActionButton {
                    objectName: "turnoutSubmit"
                    visible: page.draft
                    text: page.t("turnout_submit")
                    working: page.editorState.busy
                    enabled: page.editable && page.selected.status === "draft"
                        && !page.editorState.dirty && !page.editorState.newer_revision
                    onClicked: page.turnout.submit()
                }
                ActionButton {
                    objectName: "turnoutAmend"
                    visible: page.amendable
                    text: page.t("turnout_amend")
                    working: page.editorState.busy
                    enabled: page.editable && page.amendable && !page.editorState.newer_revision
                        && !!(page.form.amendment_reason || "").trim()
                    onClicked: page.turnout.amend()
                }
            }
        }
    }

    FormPanel {
        visible: page.hasStation && !!page.selected.source_basis_display
        implicitHeight: sourceBasisLayout.implicitHeight + 40
        ColumnLayout {
            id: sourceBasisLayout
            anchors.fill: parent
            anchors.margins: 20
            spacing: 16
            Heading { text: page.t("turnout_frozen_source_basis") }
            Detail {
                objectName: "turnoutActivationReference"
                caption: page.t("turnout_activation_reference")
                value: page.exact(page.sourceBasis.activation_id) + " · "
                    + page.t("revision") + " " + page.exact(page.sourceBasis.activation_revision)
                    + " · " + page.time((page.sourceBasis.activation || ({})).event_at)
            }
            GridLayout {
                Layout.fillWidth: true
                columns: page.width > 900 ? 3 : 1
                columnSpacing: 24
                rowSpacing: 16
                Detail {
                    objectName: "turnoutBaseline"
                    caption: page.t("turnout_activation_baseline")
                    value: page.exact((page.sourceBasis.activation || ({})).cumulative_quantity_display)
                }
                Detail {
                    objectName: "turnoutOrdinaryDelta"
                    caption: page.t("turnout_ordinary_delta")
                    value: page.exact(page.sourceBasis.ordinary_issued_since_activation_quantity_display)
                }
                Detail {
                    objectName: "turnoutStockCumulative"
                    caption: page.t("turnout_stock_cumulative")
                    value: page.exact(page.sourceBasis.stock_derived_cumulative_quantity_display)
                }
                Detail {
                    objectName: "turnoutRecoveredCumulative"
                    visible: page.sourceBasis.recovered_cumulative_quantity_display !== undefined
                    caption: page.t("turnout_recovered_cumulative")
                    value: page.exact(page.sourceBasis.recovered_cumulative_quantity_display)
                }
                Detail {
                    objectName: "turnoutReconciliationDifference"
                    visible: page.sourceBasis.reconciliation_difference_display !== undefined
                    caption: page.t("turnout_reconciliation_difference")
                    value: page.exact(page.sourceBasis.reconciliation_difference_display)
                }
            }
            Repeater {
                model: page.sourceBasis.coverage || []
                delegate: Detail {
                    required property var modelData
                    required property int index
                    objectName: "turnoutCoverage" + index
                    caption: page.t("turnout_interval_" + modelData.mode) + " · "
                        + page.time(modelData.start_at) + " → " + page.time(modelData.end_at)
                    value: page.exact(modelData.cumulative_start_quantity_display) + " → "
                        + page.exact(modelData.cumulative_end_quantity_display) + " · "
                        + page.t("turnout_coverage_hourly") + " "
                        + page.exact(modelData.hourly_quantity_display)
                }
            }
        }
    }

    FormPanel {
        visible: page.hasStation && page.supervisor && page.hasReviewedPeriod
        implicitHeight: approval.implicitHeight + 40
        ColumnLayout {
            id: approval
            anchors.fill: parent
            anchors.margins: 20
            spacing: 12
            Heading { text: page.t("turnout_approve") }
            FormCaption { text: page.t("turnout_approval_hint") }
            FormCaption {
                text: page.t("turnout_period") + " " + page.reviewedPeriod.period_index
                    + " · " + page.t("revision") + " " + (page.selected.revision || "—")
            }
            FormCaption { text: page.t("approval_password") }
            FormField {
                id: approvalPassword
                objectName: "turnoutApprovalPassword"
                echoMode: TextInput.Password
                maximumLength: 128
                working: page.editorState.busy
                enabled: page.canApprove
                Accessible.name: page.t("approval_password")
                onReveal: control => page.reveal(control)
            }
            ActionButton {
                objectName: "turnoutApprove"
                text: page.t("turnout_approve")
                working: page.editorState.busy
                enabled: page.canApprove && approvalPassword.text.length > 0
                onClicked: page.turnout.approve(approvalPassword.text)
            }
        }
    }

    FormPanel {
        visible: page.hasStation
        implicitHeight: historyLayout.implicitHeight + 40
        ColumnLayout {
            id: historyLayout
            anchors.fill: parent
            anchors.margins: 20
            spacing: 20
            Heading { text: page.t("turnout_history") }
            FormCaption {
                visible: page.editorState.history.length === 0
                text: page.t(page.editorState.busy || page.editorState.refreshing ? "loading" : "turnout_no_history")
            }
            Repeater {
                model: page.editorState.history
                delegate: ColumnLayout {
                    id: entry
                    required property var modelData
                    Layout.fillWidth: true
                    spacing: 12
                    Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: "#e1e7f0" }
                    Heading {
                        text: page.t("revision") + " " + entry.modelData.revision
                            + " · " + page.t(entry.modelData.status)
                        font.pixelSize: 17
                    }
                    ActionButton {
                        objectName: "turnoutHistoryRevision" + entry.modelData.revision
                        text: page.t("turnout_view_revision") + " · " + page.t("revision") + " " + entry.modelData.revision
                        highlighted: false
                        flat: true
                        working: page.editorState.busy
                        onClicked: page.choose("revision", entry.modelData.revision)
                    }
                    GridLayout {
                        Layout.fillWidth: true
                        columns: page.width > 780 ? 2 : 1
                        columnSpacing: 24
                        rowSpacing: 16
                        Detail { caption: page.t("turnout_supplied_hourly"); value: entry.modelData.supplied_hourly_display || "—" }
                        Detail { caption: page.t("turnout_supplied_cumulative"); value: entry.modelData.supplied_cumulative_display || "—" }
                        Detail { caption: page.t("turnout_derived_hourly"); value: entry.modelData.derived_hourly_display || "—" }
                        Detail { caption: page.t("turnout_derived_start"); value: entry.modelData.derived_cumulative_start_display || "—" }
                        Detail { caption: page.t("turnout_derived_end"); value: entry.modelData.derived_cumulative_end_display || "—" }
                        Detail { caption: page.t("turnout_basis_revision"); value: page.basis(entry.modelData) }
                        Detail { caption: page.t("turnout_event_time"); value: page.time(entry.modelData.event_at) }
                        Detail {
                            caption: page.t("server_entry")
                            value: page.time(entry.modelData.entered_at) + "\n"
                                + page.t("entered_by") + " " + entry.modelData.actor_id
                        }
                        Detail {
                            caption: page.t("submission")
                            value: entry.modelData.submitted_at ? page.time(entry.modelData.submitted_at)
                                + "\n" + page.t("submitted_by") + " " + entry.modelData.submitted_by : "—"
                        }
                        Detail {
                            caption: page.t("approval")
                            value: entry.modelData.approved_at ? page.time(entry.modelData.approved_at)
                                + "\n" + page.t("approved_by") + " " + entry.modelData.approved_by : "—"
                        }
                    }
                    Detail { caption: page.t("turnout_source_context"); value: entry.modelData.source_context || "—" }
                    Detail { caption: page.t("amendment_reason"); value: entry.modelData.amendment_reason || "—" }
                }
            }
        }
    }

    FormPanel {
        visible: page.hasStation
        implicitHeight: reportLayout.implicitHeight + 40
        ColumnLayout {
            id: reportLayout
            anchors.fill: parent
            anchors.margins: 20
            spacing: 12
            Heading { text: page.t("turnout_report") }
            FormCaption { text: page.t("turnout_report_hint") }
            FormCaption { text: page.t("turnout_report_scope") }
            ComboBox {
                id: reportScope
                objectName: "turnoutReportScope"
                Layout.fillWidth: true
                model: [page.t("turnout_report_selected"), page.t("turnout_report_station")]
                enabled: !page.editorState.busy
                implicitHeight: Math.max(48, scopeText.implicitHeight + 24)
                Accessible.name: page.t("turnout_report_scope")
                contentItem: Text {
                    id: scopeText
                    text: reportScope.displayText
                    textFormat: Text.PlainText
                    font: reportScope.font
                    color: "#25344b"
                    wrapMode: Text.WordWrap
                    verticalAlignment: Text.AlignVCenter
                }
                delegate: ItemDelegate {
                    id: scopeOption
                    required property string modelData
                    required property int index
                    width: reportScope.width
                    highlighted: reportScope.highlightedIndex === index
                    implicitHeight: Math.max(48, scopeOptionText.implicitHeight + 20)
                    contentItem: Text {
                        id: scopeOptionText
                        text: scopeOption.modelData
                        textFormat: Text.PlainText
                        font: scopeOption.font
                        color: "#25344b"
                        wrapMode: Text.WordWrap
                        verticalAlignment: Text.AlignVCenter
                    }
                }
                onActiveFocusChanged: if (activeFocus) Qt.callLater(function() {
                    if (reportScope.activeFocus) page.reveal(reportScope)
                })
            }
            FormCaption {
                text: page.t(reportScope.currentIndex === 1
                    ? "turnout_report_station_hint" : "turnout_report_selected_hint")
            }
            FormCaption {
                visible: reportScope.currentIndex === 0 && !page.selected.revision
                text: page.t("turnout_report_missing")
            }
            FormCaption {
                text: page.t("stock_report_language") + " · " + page.languageName(page.locale)
            }
            GridLayout {
                Layout.fillWidth: true
                columns: page.width > 900 ? 3 : 1
                columnSpacing: 12
                rowSpacing: 8
                ActionButton {
                    objectName: "turnoutPreview"
                    text: page.t("stock_preview")
                    working: page.editorState.busy
                    enabled: !working && (reportScope.currentIndex === 1 || !!page.selected.revision)
                    onClicked: page.previewReport()
                }
                ActionButton {
                    objectName: "turnoutExportPdf"
                    text: page.t("stock_export_pdf")
                    working: page.editorState.busy
                    highlighted: false
                    enabled: !working && (reportScope.currentIndex === 1 || !!page.selected.revision)
                    onClicked: page.exportReport("pdf")
                }
                ActionButton {
                    objectName: "turnoutExportCsv"
                    text: page.t("stock_export_csv")
                    working: page.editorState.busy
                    highlighted: false
                    enabled: !working && (reportScope.currentIndex === 1 || !!page.selected.revision)
                    onClicked: page.exportReport("csv")
                }
            }
            FormCaption {
                visible: !!page.editorState.report_text
                text: page.t("stock_preview_language") + " · "
                    + page.languageName((page.editorState.report || ({})).locale || page.locale)
                    + "\n" + page.t((page.editorState.report || ({})).report_scope === "station_current"
                        ? "turnout_report_station" : "turnout_report_selected")
            }
            ReasonTextArea {
                objectName: "turnoutReportPreview"
                visible: !!page.editorState.report_text
                readOnly: true
                text: page.editorState.report_text || ""
                caption: page.t("turnout_report")
            }
            FormCaption {
                visible: !!page.editorState.export_path
                text: page.t("stock_export_location") + "\n" + (page.editorState.export_path || "")
            }
        }
    }

    ConfirmationDialog {
        id: discardDialog
        objectName: "turnoutDiscardDialog"
        title: page.t("discard_changes")
        message: page.t("unsaved_turnout_changes")
        acceptLabel: page.t("discard_changes")
        rejectLabel: page.t("keep_editing")
        onConfirmed: {
            if (page.pendingAction === "period") page.turnout.selectPeriod(page.pendingValue, true)
            else if (page.pendingAction === "page") page.turnout.setPage(page.pendingValue, true)
            else if (page.pendingAction === "revision") page.turnout.loadRevision(page.pendingValue, true)
            else page.turnout.reload(true)
            page.restorePicker()
        }
    }
    FileDialog {
        id: exportDialog
        objectName: "turnoutExportDialog"
        title: page.t(page.pendingFormat === "pdf" ? "stock_export_pdf" : "stock_export_csv")
        fileMode: FileDialog.SaveFile
        currentFolder: StandardPaths.writableLocation(StandardPaths.DocumentsLocation)
        onAccepted: page.turnout.download(page.pendingFormat, selectedFile.toString(),
            page.pendingLocale, page.pendingStationReport)
    }
}

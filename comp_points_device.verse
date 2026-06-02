using { /Fortnite.com/Devices }
using { /Fortnite.com/Characters }
using { /Fortnite.com/Playspaces }
using { /Fortnite.com/UI }
using { /UnrealEngine.com/Temporary/UI }
using { /Verse.org/Colors }
using { /Verse.org/Simulation }

# Drop this device into your UEFN level.
# Assign BadgeEmpty and BadgeFilled textures in the editor
# (import the two pentagon PNGs from the images provided).
comp_points_device := class(creative_device):

    # How many points per elimination
    @editable
    PointsPerElimination : int = 1

    # Pentagon texture when player has 0 points (light gold)
    @editable
    BadgeEmpty : texture = DefaultCreativeTexture

    # Pentagon texture when player has 1+ points (dark bronze)
    @editable
    BadgeFilled : texture = DefaultCreativeTexture

    # Internal state
    var PlayerPoints  : [player]int    = map{}
    var PlayerWidgets : [player]canvas = map{}

    OnBegin<override>()<suspends> : void =
        Playspace := GetPlayspace()
        Playspace.PlayerAddedEvent().Subscribe(OnPlayerAdded)
        for (P : Playspace.GetPlayers()):
            InitPlayer(P)

    OnPlayerAdded(P : player) : void =
        InitPlayer(P)

    InitPlayer(P : player) : void =
        if (set PlayerPoints[P] = 0):
            UpdateHUD(P, 0)
        if (Char := P.GetFortCharacter[]):
            Char.EliminatedEvent().Subscribe(OnEliminated)

    OnEliminated(Result : elimination_result) : void =
        if (EliminatorAgent := Result.EliminatingCharacter?.GetAgent[]):
            if (EliminatorPlayer := player[EliminatorAgent]):
                OldPoints := if (Pts := PlayerPoints[EliminatorPlayer]) then Pts else 0
                NewPoints := OldPoints + PointsPerElimination
                if (set PlayerPoints[EliminatorPlayer] = NewPoints):
                    UpdateHUD(EliminatorPlayer, NewPoints)

    # Call this from other devices to add points manually
    AddPoints(P : player, Amount : int) : void =
        OldPoints := if (Pts := PlayerPoints[P]) then Pts else 0
        NewPoints := OldPoints + Amount
        if (set PlayerPoints[P] = NewPoints):
            UpdateHUD(P, NewPoints)

    # Build the badge overlay (pentagon + number stacked)
    MakeBadgeWidget(Points : int) : canvas =
        # Pick texture based on whether player has points
        BadgeTexture := if (Points > 0) then BadgeFilled else BadgeEmpty

        Badge := texture_block:
            DefaultImage := BadgeTexture
            DefaultDesiredSize := vector2{X := 72.0, Y := 72.0}

        PointsLabel := text_block:
            DefaultText := "{Points}"
            DefaultTextColor := color{R := 1.0, G := 1.0, B := 1.0, A := 1.0}
            DefaultShadowColor := color{R := 0.0, G := 0.0, B := 0.0, A := 1.0}
            DefaultShadowOffset := option{vector2{X := 1.5, Y := 1.5}}
            DefaultJustification := text_justification.Center

        # Stack text centred on top of the pentagon badge
        BadgeOverlay := overlay:
            Slots := array:
                overlay_slot:
                    Widget := Badge
                    HorizontalAlignment := horizontal_alignment.Center
                    VerticalAlignment := vertical_alignment.Center
                overlay_slot:
                    Widget := PointsLabel
                    HorizontalAlignment := horizontal_alignment.Center
                    VerticalAlignment := vertical_alignment.Center

        # Anchor to bottom-left of screen
        canvas:
            Slots := array:
                canvas_slot:
                    Anchors := anchors{
                        Minimum := vector2{X := 0.03, Y := 0.88}
                        Maximum := vector2{X := 0.03, Y := 0.88}
                    }
                    Alignment := vector2{X := 0.0, Y := 1.0}
                    SizeToContent := true
                    Widget := BadgeOverlay

    UpdateHUD(P : player, Points : int) : void =
        if (UI := GetPlayerUI[player_ui, P]):
            # Remove old badge before drawing new one
            if (OldWidget := PlayerWidgets[P]):
                UI.RemoveWidget(OldWidget)
            NewWidget := MakeBadgeWidget(Points)
            if (set PlayerWidgets[P] = NewWidget):
                UI.AddWidget(NewWidget, player_ui_slot{ZOrder := 2, InputMode := ui_input_mode.None})

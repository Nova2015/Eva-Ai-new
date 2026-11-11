// Frontend/src/components/AttackChart.js

import React from "react";

const AttackChart = ({ attacks }) => {

    const total = attacks.length;

    return (

        <div
            style={{
                background: "#111",
                color: "#fff",
                padding: "20px",
                borderRadius: "10px"
            }}
        >

            <h2>Attack Monitor</h2>

            <div
                style={{
                    display: "flex",
                    gap: "10px",
                    marginTop: "20px"
                }}
            >

                {attacks.map((attack, index) => (

                    <div
                        key={index}
                        style={{
                            width: "60px",
                            height: `${attack.count * 20}px`,
                            background: "red",
                            display: "flex",
                            alignItems: "flex-end",
                            justifyContent: "center",
                            color: "#fff",
                            borderRadius: "6px"
                        }}
                    >
                        {attack.count}
                    </div>

                ))}

            </div>

            <p style={{ marginTop: "20px" }}>
                Total Attacks: {total}
            </p>

        </div>
    );
};

export default AttackChart;